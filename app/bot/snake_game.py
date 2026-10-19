"""بازی مار و پله فوق حرفه‌ای، جمع‌وجور و کاملاً ضد اسپم (Anti-Flood)"""

import random
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

LADDERS = {2: 38, 7: 14, 8: 31, 15: 26, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 78: 98}
SNAKES = {16: 6, 46: 25, 49: 11, 62: 19, 64: 60, 74: 53, 89: 68, 92: 88, 95: 75, 99: 80}

ACTIVE_GAMES = {}
PLAYER_ICONS = ["🦊", "🐼", "🦁", "🐸"]
TURN_TIMEOUT = 30 

def _draw_compact_board(players: list) -> str:
    """نقشه فشرده، جدول‌بندی شده و مرتب"""
    cells = {}
    for start in LADDERS: cells[start] = "🪜"
    for start in SNAKES: cells[start] = "🐍"
    for p in players:
        if p["pos"] > 0: cells[p["pos"]] = p["icon"]

    lines = ["<pre>"]
    for row in range(10, 0, -1):
        line = ""
        cols = range(1, 11) if row % 2 != 0 else range(10, 0, -1)
        for col in cols:
            pos = (row - 1) * 10 + col
            val = cells.get(pos)
            if val: 
                line += f"[{val} ]"
            else: 
                line += f"[{pos:02d} ]" if pos < 100 else "[100]"
        lines.append(line)
    lines.append("</pre>")
    return "\n".join(lines)

def _get_game_ui(game: dict) -> str:
    """رابط کاربری تمیز و هیجانی بدون شلوغی"""
    if game["status"] == "lobby":
        text = "🐍 <b>لابی بازی مار و پله</b> 🪜\n\n"
        for p in game["players"]: text += f"👤 {p['icon']} {p['name']}\n"
        text += "\n👇 برای ورود یا بازی با ربات کلیک کنید."
        return text
    
    current = game["players"][game["turn_index"]]
    
    # هدر (نوبت)
    if current["id"] == -1:
        header = f"🤖 <b>ربات در حال فکر کردن...</b>"
    else:
        dice_info = f" (🎲 {game['last_dice']})" if game.get('last_dice') else ""
        header = f"🎲 <b>نوبت:</b> {current['icon']} {current['name']}{dice_info}"

    # نقشه
    map_text = _draw_compact_board(game["players"])
    
    # آمار بازیکنان با دایره‌های نوبت
    stats = "\n📊 <b>آمار بازیکنان:</b>\n"
    for idx, p in enumerate(game["players"]):
        circle = "🟢" if idx == game["turn_index"] else "⚪"
        # نمایش تاس فقط برای کسی که نوبتشه
        dice_text = f"🎲{game['last_dice']}" if idx == game["turn_index"] and game.get('last_dice') else "  "
        pos = "🏁 برنده!" if p["pos"] == 100 else f"خانه {p['pos']}"
        stats += f"{circle} {p['icon']} {p['name']} | {dice_text} | {pos}\n"
        
    # رویدادها
    events = "\n📢 <b>آخرین رویداد:</b>\n"
    if game.get("last_action"):
        events += f"<i>{game['last_action']}</i>"

    return f"{header}\n\n{map_text}\n{stats}{events}"

def _get_lobby_keyboard(game: dict) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🎮 ورود به بازی", callback_data="snake_join")],
        [InlineKeyboardButton("🤖 بازی با ربات", callback_data="snake_play_bot")]
    ]
    if len(game["players"]) >= 2:
        kb.append([InlineKeyboardButton("🚀 شروع بازی", callback_data="snake_start")])
    return InlineKeyboardMarkup(kb)

def _get_game_keyboard(is_locked: bool = False) -> InlineKeyboardMarkup:
    if is_locked:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⏳ در حال حرکت...", callback_data="snake_wait")]])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 پرتاب تاس", callback_data="snake_roll")],
        [InlineKeyboardButton("❌ انصراف", callback_data="snake_surrender")]
    ])

async def _auto_roll_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    """تایمر پس‌زمینه: اگر ۳۰ ثانیه کسی تاس ننداخت، خودکار می‌ریزد"""
    job = context.job
    game = ACTIVE_GAMES.get(job.chat_id)
    if not game or game["status"] != "playing" or game.get("is_rolling"): return
    
    current = game["players"][game["turn_index"]]
    if current["id"] == job.data:
        game["last_action"] = f"⏰ زمان {current['name']} تمام شد! ربات تاس می‌ریزد..."
        try:
            await context.bot.edit_message_text(chat_id=job.chat_id, message_id=game["message_id"], text=_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(True))
        except: pass
        await asyncio.sleep(1)
        await _process_roll(context, job.chat_id, game["message_id"], current["id"], is_auto=True)

async def _bot_roll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """نوبت ربات"""
    job = context.job
    game = ACTIVE_GAMES.get(job.chat_id)
    if game and game["status"] == "playing" and game["players"][game["turn_index"]]["id"] == -1:
        await _process_roll(context, job.chat_id, game["message_id"], -1, is_auto=True)

async def _process_roll(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int, user_id: int, is_auto=False) -> None:
    """منطق اصلی با قفل ضد اسپم"""
    game = ACTIVE_GAMES.get(chat_id)
    if not game or game["status"] != "playing" or game.get("is_rolling"): return
    
    current = game["players"][game["turn_index"]]
    if current["id"] != user_id: return

    # 🔒 قفل کردن بازی برای جلوگیری از اسپم
    game["is_rolling"] = True
    
    # حذف تایمرها
    for job in context.job_queue.get_jobs_by_name(f"snake_timer_{chat_id}"): job.schedule_removal()
    for job in context.job_queue.get_jobs_by_name(f"snake_bot_{chat_id}"): job.schedule_removal()

    # ریختن تاس
    dice = random.randint(1, 6)
    game["last_dice"] = dice
    game["last_action"] = f"{current['name']} در حال حرکت..."
    
    try:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(True))
    except: pass
    await asyncio.sleep(1.0) # تاخیر هیجانی

    old_pos = current["pos"]
    target_pos = old_pos + dice
    
    if target_pos > 100:
        game["last_action"] = f"❌ {current['name']} تاس {dice} آورد اما از ۱۰۰ رد شد."
    else:
        # 🏃‍♂️ انیمیشن حرکت (۱ ثانیه تاخیر برای امنیت کامل)
        for step in range(old_pos + 1, target_pos + 1):
            current["pos"] = step
            game["last_action"] = f"➡️ {current['name']} به خانه {step} رفت."
            try:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(True))
            except: pass
            await asyncio.sleep(1.0) # ۱ ثانیه تاخیر ضد اسپم

        # 💥 برخورد
        for p in game["players"]:
            if p["id"] != current["id"] and p["pos"] == target_pos:
                p["pos"] = 0
                game["last_action"] = f"💥 {current['name']} زد به {p['name']} و فرستادش خانه ۱!"
                try: await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(True))
                except: pass
                await asyncio.sleep(1.5)

        # 🐍 مار و 🪜 پله
        if target_pos in LADDERS:
            game["last_action"] = f"🪜 {current['name']} پله رفت! به {LADDERS[target_pos]}"
            await asyncio.sleep(1.0)
            current["pos"] = LADDERS[target_pos]
            try: await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(True))
            except: pass
        elif target_pos in SNAKES:
            game["last_action"] = f"🐍 {current['name']} مار خورد! به {SNAKES[target_pos]}"
            await asyncio.sleep(1.0)
            current["pos"] = SNAKES[target_pos]
            try: await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(True))
            except: pass

    game["last_action"] = f"🎲 {current['name']} تاس {dice} آورد."
    
    # بررسی برد
    if current["pos"] == 100:
        game["status"] = "finished"
        game["last_action"] = f"🏆 <b>{current['name']} برنده شد!</b> 🎉"
        try: await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=None)
        except: pass
        del ACTIVE_GAMES[chat_id]
        return

    # تغییر نوبت
    if dice != 6: game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
    else: game["last_action"] += " (چون ۶ آورد، دوباره می‌ندازه!)"

    next_player = game["players"][game["turn_index"]]
    game["is_rolling"] = False # 🔓 باز کردن قفل
    
    try: await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(False))
    except: pass

    # شروع تایمر جدید (فقط در پس‌زمینه)
    if next_player["id"] == -1:
        context.job_queue.run_once(_bot_roll_job, when=2.0, chat_id=chat_id, name=f"snake_bot_{chat_id}")
    else:
        context.job_queue.run_once(_auto_roll_timeout, when=TURN_TIMEOUT, chat_id=chat_id, data=next_player["id"], name=f"snake_timer_{chat_id}")

async def cmd_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور شروع بازی (در گروه و پی‌وی)"""
    chat_id = update.effective_chat.id
    if chat_id in ACTIVE_GAMES: 
        await update.message.reply_text("⚠️ یک بازی در جریان است!"); return
    
    ACTIVE_GAMES[chat_id] = {
        "status": "lobby", "host_id": update.effective_user.id, 
        "players": [{"id": update.effective_user.id, "name": update.effective_user.first_name, "pos": 0, "icon": PLAYER_ICONS[0]}],
        "turn_index": 0, "last_action": "بازی ساخته شد.", "is_rolling": False, "last_dice": None, "message_id": None
    }
    msg = await update.message.reply_text(_get_game_ui(ACTIVE_GAMES[chat_id]), parse_mode="HTML", reply_markup=_get_lobby_keyboard(ACTIVE_GAMES[chat_id]))
    ACTIVE_GAMES[chat_id]["message_id"] = msg.message_id

async def handle_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; chat_id = update.effective_chat.id; user = update.effective_user
    if chat_id not in ACTIVE_GAMES: 
        await query.answer("بازی تمام شده است.", show_alert=True); return
    
    game = ACTIVE_GAMES[chat_id]; msg_id = game["message_id"]

    if query.data == "snake_join":
        if game.get("is_rolling"): return await query.answer("بازی در حال حرکت است، صبر کنید!", show_alert=True)
        if any(p["id"] == user.id for p in game["players"]): return await query.answer("شما قبلاً وارد شده‌اید.", show_alert=True)
        if len(game["players"]) >= 4: return await query.answer("ظرفیت پر است.", show_alert=True)
        
        game["players"].append({"id": user.id, "name": user.first_name, "pos": 0, "icon": PLAYER_ICONS[len(game["players"])]})
        await query.answer("✅ وارد شدید!")
        try: await query.edit_message_text(_get_game_ui(game), parse_mode="HTML", reply_markup=_get_lobby_keyboard(game))
        except: pass
        return

    if query.data == "snake_play_bot":
        if game["status"] != "lobby": return await query.answer("بازی شروع شده است!", show_alert=True)
        
        game["players"].append({"id": -1, "name": "ربات", "pos": 0, "icon": "🤖"})
        game["status"] = "playing"; game["turn_index"] = 0; game["last_action"] = "بازی با ربات شروع شد!"
        await query.answer("بازی شروع شد!")
        try: await query.edit_message_text(_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(False))
        except: pass
        context.job_queue.run_once(_auto_roll_timeout, when=TURN_TIMEOUT, chat_id=chat_id, data=game["players"][0]["id"], name=f"snake_timer_{chat_id}")
        return

    if query.data == "snake_start":
        if game.get("is_rolling"): return await query.answer("بازی در حال حرکت است!", show_alert=True)
        if user.id != game["host_id"] or len(game["players"]) < 2: 
            return await query.answer("شرایط شروع فراهم نیست.", show_alert=True)
        
        game["status"] = "playing"; game["turn_index"] = 0; game["last_action"] = "بازی شروع شد!"
        await query.answer("بازی شروع شد!")
        try: await query.edit_message_text(_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(False))
        except: pass
        context.job_queue.run_once(_auto_roll_timeout, when=TURN_TIMEOUT, chat_id=chat_id, data=game["players"][0]["id"], name=f"snake_timer_{chat_id}")
        return

    if query.data == "snake_surrender":
        if game.get("is_rolling"): return await query.answer("بازی در حال حرکت است!", show_alert=True)
        p_idx = next((i for i, p in enumerate(game["players"]) if p["id"] == user.id), None)
        if p_idx is not None:
            s_p = game["players"].pop(p_idx); await query.answer("شما خارج شدید.")
            if len(game["players"]) < 2: 
                del ACTIVE_GAMES[chat_id]; 
                try: await query.edit_message_text(f"🏳️ {s_p['name']} انصراف داد. بازی لغو شد.")
                except: pass
                return
            if game["turn_index"] >= len(game["players"]): game["turn_index"] = 0
            try: await query.edit_message_text(_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(False))
            except: pass
        return

    if query.data == "snake_roll":
        if game.get("is_rolling"): return await query.answer("لطفاً صبر کنید، در حال حرکت است!", show_alert=True)
        if game["status"] != "playing" or user.id != game["players"][game["turn_index"]]["id"]:
            return await query.answer("نوبت شما نیست!", show_alert=True)
        
        await query.answer("🎲 در حال پرتاب تاس...")
        await _process_roll(context, chat_id, msg_id, user.id)
        return
