"""بازی مار و پله حرفه‌ای، سریع و با دکمه‌های اختصاصی"""

import random
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

# تنظیمات نقشه ۸×۸
LADDERS = {4: 14, 8: 26, 20: 38, 30: 44, 42: 56, 50: 58}
SNAKES = {15: 3, 25: 12, 36: 18, 48: 30, 55: 40, 62: 52}
DRAGONS = {10: 2, 32: 16, 45: 28}
MAX_POS = 64

ACTIVE_GAMES = {}
PLAYER_ICONS = ["🦊", "🐼", "🦁", "🐸"]
TURN_TIMEOUT = 30 

def _draw_simple_map(players: list) -> str:
    """نقشه جمع‌وجور و تمیز"""
    cells = {}
    for start in LADDERS: cells[start] = "🪜"
    for start in SNAKES: cells[start] = "🐍"
    for start in DRAGONS: cells[start] = "🐉"
    for p in players:
        if p["pos"] > 0: cells[p["pos"]] = p["icon"]

    lines = ["<pre>"] # استفاده از pre برای هم‌ترازی، اگر دکمه کپی اذیت میکنه میشه حذفش کرد
    for row in range(8, 0, -1):
        line = ""
        cols = range(1, 9) if row % 2 != 0 else range(8, 0, -1)
        for col in cols:
            pos = (row - 1) * 8 + col
            val = cells.get(pos)
            if val: line += f" {val} "
            else: line += f" {pos:02d} "
        lines.append(line.strip())
    lines.append("</pre>")
    return "\n".join(lines)

def _get_game_ui(game: dict) -> str:
    """رابط کاربری سریع و تمیز"""
    if game["status"] == "lobby":
        text = "🐍 <b>لابی بازی مار و پله</b> 🪜🐉\n\n"
        text += f"👥 بازیکنان ({len(game['players'])}/4):\n"
        for p in game["players"]: text += f"👤 {p['icon']} {p['name']}\n"
        text += "\n👇 برای ورود کلیک کنید. (منتظر ۶ باشید)"
        return text
    
    current = game["players"][game["turn_index"]]
    header = "🤖 <b>ربات در حال فکر کردن...</b>" if current["id"] == -1 else f"🎲 <b>نوبت:</b> {current['icon']} {current['name']}"
    if current["id"] != -1 and game.get('last_dice'): header += f" (🎲 {game['last_dice']})"

    map_text = _draw_simple_map(game["players"])
    
    stats = "\n📊 <b>آمار:</b>\n"
    for idx, p in enumerate(game["players"]):
        circle = "🟢" if idx == game["turn_index"] else "⚪"
        dice_text = f"🎲{game['last_dice']}" if idx == game["turn_index"] and game.get('last_dice') else "  "
        if p["pos"] == 0: pos = "⏳ منتظر ۶"
        elif p["pos"] == MAX_POS: pos = "🏆 برنده!"
        else: pos = f"خانه {p['pos']}"
        stats += f"{circle} {p['icon']} {p['name']} | {dice_text} | {pos}\n"
        
    events = f"\n📢 <i>{game.get('last_action', '')}</i>"
    return f"{header}\n\n{map_text}{stats}{events}"

def _get_lobby_keyboard(game: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎮 ورود به بازی ({len(game['players'])}/4)", callback_data="snake_join")],
        [InlineKeyboardButton("🤖 بازی با ربات", callback_data="snake_play_bot")],
        [InlineKeyboardButton("🚀 شروع بازی", callback_data="snake_start")] if len(game["players"]) >= 2 else []
    ])

def _get_game_keyboard(game: dict) -> InlineKeyboardMarkup:
    """دکمه‌های حین بازی (ورود، آپدیت، تاس، انصراف)"""
    kb = []
    # دکمه ورود جدید (اگر ظرفیت داشته باشه)
    if len(game["players"]) < 4:
        kb.append([InlineKeyboardButton(f"🎮 ورود به بازی ({len(game['players'])}/4)", callback_data="snake_join")])
        
    kb.append([InlineKeyboardButton("🎲 پرتاب تاس", callback_data="snake_roll")])
    kb.append([InlineKeyboardButton("🔄 آوردن به پایین", callback_data="snake_bump")])
    kb.append([InlineKeyboardButton("❌ انصراف", callback_data="snake_surrender")])
    return InlineKeyboardMarkup(kb)

async def _auto_roll_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job; game = ACTIVE_GAMES.get(job.chat_id)
    if not game or game["status"] != "playing" or game.get("is_rolling"): return
    current = game["players"][game["turn_index"]]
    if current["id"] == job.data:
        game["last_action"] = f"⏰ زمان {current['name']} تمام شد!"
        await _process_roll(context, job.chat_id, game["message_id"], current["id"])

async def _bot_roll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job; game = ACTIVE_GAMES.get(job.chat_id)
    if game and game["status"] == "playing" and game["players"][game["turn_index"]]["id"] == -1:
        await _process_roll(context, job.chat_id, game["message_id"], -1)

async def _process_roll(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int, user_id: int) -> None:
    game = ACTIVE_GAMES.get(chat_id)
    if not game or game["status"] != "playing" or game.get("is_rolling"): return
    current = game["players"][game["turn_index"]]
    if current["id"] != user_id: return

    game["is_rolling"] = True
    for job in context.job_queue.get_jobs_by_name(f"snake_timer_{chat_id}"): job.schedule_removal()
    for job in context.job_queue.get_jobs_by_name(f"snake_bot_{chat_id}"): job.schedule_removal()

    dice = random.randint(1, 6)
    game["last_dice"] = dice
    old_pos = current["pos"]
    
    if old_pos == 0 and dice != 6:
        game["last_action"] = f"🔒 {current['name']} برای ورود باید ۶ بیاورد! (تاس: {dice})"
    else:
        target_pos = old_pos + dice
        if target_pos > MAX_POS:
            target_pos = MAX_POS - (target_pos - MAX_POS)
            game["last_action"] = f"🔄 {current['name']} تاس {dice} آورد، برگشت به {target_pos}."
        else:
            game["last_action"] = f"➡️ {current['name']} تاس {dice} آورد، به خانه {target_pos} رفت."
        
        current["pos"] = target_pos
        
        # برخورد
        for p in game["players"]:
            if p["id"] != current["id"] and p["pos"] == target_pos:
                p["pos"] = 0
                game["last_action"] = f"💥 {current['name']} زد به {p['name']} و فرستادش خانه ۱!"

        # مار، پله، اژدها
        if target_pos in LADDERS:
            current["pos"] = LADDERS[target_pos]
            game["last_action"] = f"🪜 {current['name']} پله رفت به {current['pos']}."
        elif target_pos in SNAKES:
            current["pos"] = SNAKES[target_pos]
            game["last_action"] = f"🐍 {current['name']} مار خورد، افتاد به {current['pos']}."
        elif target_pos in DRAGONS:
            current["pos"] = DRAGONS[target_pos]
            game["last_action"] = f"🐉 {current['name']} اژدها خورد، افتاد به {current['pos']}."

    try: await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(game))
    except BadRequest: pass

    await asyncio.sleep(0.5)

    # بُرد
    if current["pos"] == MAX_POS:
        game["status"] = "finished"
        game["last_action"] = f"🏆🎉 <b>تبریک! {current['name']} برنده شد!</b> 🎉🏆\n👑 با رسیدن به خانه ۶۴ قهرمان شد."
        try: await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=None)
        except BadRequest: pass
        del ACTIVE_GAMES[chat_id]
        return

    if dice != 6: game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
    else: game["last_action"] += " (دوباره تاس می‌ندازه!)"

    next_player = game["players"][game["turn_index"]]
    game["is_rolling"] = False
    
    try: await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(game))
    except BadRequest: pass

    if next_player["id"] == -1:
        context.job_queue.run_once(_bot_roll_job, when=1.5, chat_id=chat_id, name=f"snake_bot_{chat_id}")
    else:
        context.job_queue.run_once(_auto_roll_timeout, when=TURN_TIMEOUT, chat_id=chat_id, data=next_player["id"], name=f"snake_timer_{chat_id}")

async def cmd_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in ACTIVE_GAMES: return await update.message.reply_text("⚠️ یک بازی در جریان است!")
    ACTIVE_GAMES[chat_id] = {"status": "lobby", "host_id": update.effective_user.id, "players": [{"id": update.effective_user.id, "name": update.effective_user.first_name, "pos": 0, "icon": PLAYER_ICONS[0]}], "turn_index": 0, "last_action": "بازی ساخته شد.", "is_rolling": False, "last_dice": None, "message_id": None}
    msg = await update.message.reply_text(_get_game_ui(ACTIVE_GAMES[chat_id]), parse_mode="HTML", reply_markup=_get_lobby_keyboard(ACTIVE_GAMES[chat_id]))
    ACTIVE_GAMES[chat_id]["message_id"] = msg.message_id

async def handle_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; chat_id = update.effective_chat.id; user = update.effective_user
    if chat_id not in ACTIVE_GAMES: return await query.answer("بازی تمام شده است.", show_alert=True)
    game = ACTIVE_GAMES[chat_id]; msg_id = game["message_id"]

    # 🔄 آوردن به پایین (فقط بازیکنان)
    if query.data == "snake_bump":
        if not any(p["id"] == user.id for p in game["players"]):
            return await query.answer("فقط بازیکنان می‌توانند بازی را آپدیت کنند!", show_alert=True)
        
        await query.answer("بازی آپدیت شد.")
        try: await query.message.delete() 
        except: pass
        
        # ارسال پیام جدید به پایین‌ترین نقطه چت
        kb = _get_lobby_keyboard(game) if game["status"] == "lobby" else _get_game_keyboard(game)
        new_msg = await context.bot.send_message(chat_id=chat_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=kb)
        game["message_id"] = new_msg.message_id
        return

    # 🎮 ورود به بازی (هم در لابی هم وسط بازی)
    if query.data == "snake_join":
        if game.get("is_rolling"): return await query.answer("در حال حرکت است!", show_alert=True)
        if any(p["id"] == user.id for p in game["players"]): return await query.answer("شما قبلاً وارد شده‌اید.", show_alert=True)
        if len(game["players"]) >= 4: return await query.answer("ظرفیت پر است.", show_alert=True)
        
        game["players"].append({"id": user.id, "name": user.first_name, "pos": 0, "icon": PLAYER_ICONS[len(game["players"])]})
        await query.answer("✅ وارد شدید!")
        
        kb = _get_lobby_keyboard(game) if game["status"] == "lobby" else _get_game_keyboard(game)
        try: await query.edit_message_text(_get_game_ui(game), parse_mode="HTML", reply_markup=kb)
        except: pass
        return

    if query.data == "snake_play_bot":
        if game["status"] != "lobby": return await query.answer("شروع شده است!", show_alert=True)
        game["players"].append({"id": -1, "name": "ربات", "pos": 0, "icon": "🤖"})
        game["status"] = "playing"; game["turn_index"] = 0; game["last_action"] = "بازی شروع شد! (منتظر ۶ باشید)"
        await query.answer("شروع شد!")
        try: await query.edit_message_text(_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(game))
        except: pass
        context.job_queue.run_once(_auto_roll_timeout, when=TURN_TIMEOUT, chat_id=chat_id, data=game["players"][0]["id"], name=f"snake_timer_{chat_id}")
        return

    if query.data == "snake_start":
        if game.get("is_rolling"): return await query.answer("در حال حرکت!", show_alert=True)
        if user.id != game["host_id"] or len(game["players"]) < 2: return await query.answer("شرایط شروع فراهم نیست.", show_alert=True)
        game["status"] = "playing"; game["turn_index"] = 0; game["last_action"] = "بازی شروع شد! (منتظر ۶ باشید)"
        await query.answer("شروع شد!")
        try: await query.edit_message_text(_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(game))
        except: pass
        context.job_queue.run_once(_auto_roll_timeout, when=TURN_TIMEOUT, chat_id=chat_id, data=game["players"][0]["id"], name=f"snake_timer_{chat_id}")
        return

    if query.data == "snake_surrender":
        if game.get("is_rolling"): return await query.answer("در حال حرکت!", show_alert=True)
        p_idx = next((i for i, p in enumerate(game["players"]) if p["id"] == user.id), None)
        if p_idx is not None:
            s_p = game["players"].pop(p_idx); await query.answer("خارج شدید.")
            if len(game["players"]) < 2: 
                del ACTIVE_GAMES[chat_id]; 
                try: await query.edit_message_text(f"🏳️ {s_p['name']} انصراف داد. بازی لغو شد.")
                except: pass
                return
            if game["turn_index"] >= len(game["players"]): game["turn_index"] = 0
            try: await query.edit_message_text(_get_game_ui(game), parse_mode="HTML", reply_markup=_get_game_keyboard(game))
            except: pass
        return

    if query.data == "snake_roll":
        if game.get("is_rolling"): return await query.answer("صبر کنید...", show_alert=True)
        if game["status"] != "playing" or user.id != game["players"][game["turn_index"]]["id"]: return await query.answer("نوبت شما نیست!", show_alert=True)
        await query.answer("🎲 پرتاب شد!")
        await _process_roll(context, chat_id, msg_id, user.id)
        return
