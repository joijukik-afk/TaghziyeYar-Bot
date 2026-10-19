"""بازی مار و پله فوق حرفه‌ای، متنی و زنده"""

import random
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ChatType

logger = logging.getLogger(__name__)

# نقشه مارها و پله‌ها
LADDERS = {2: 38, 7: 14, 8: 31, 15: 26, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 78: 98}
SNAKES = {16: 6, 46: 25, 49: 11, 62: 19, 64: 60, 74: 53, 89: 68, 92: 88, 95: 75, 99: 80}

ACTIVE_GAMES = {}
PLAYER_ICONS = ["🦊", "🐼", "🦁", "🐸"] 
TURN_TIMEOUT = 30 # ثانیه برای هر نوبت

def _draw_text_board(players: list) -> str:
    """کشیدن نقشه متنی شیک"""
    cells = {}
    for start in LADDERS: cells[start] = "🪜"
    for start in SNAKES: cells[start] = "🐍"
    
    # قرار دادن بازیکنان روی نقشه
    for p in players:
        if p["pos"] > 0:
            cells[p["pos"]] = p["icon"]

    lines = ["<pre>"]
    for row in range(10, 0, -1):
        line = ""
        cols = range(1, 11) if row % 2 != 0 else range(10, 0, -1)
        for col in cols:
            pos = (row - 1) * 10 + col
            val = cells.get(pos)
            
            if val:
                line += f"[ {val} ]"
            else:
                if pos == 100:
                    line += f"[100]"
                else:
                    line += f"[{pos:02d} ]"
        lines.append(line)
    lines.append("</pre>")
    return "\n".join(lines)

def _get_game_text(game: dict) -> str:
    """ساخت رابط کاربری (UI) کامل"""
    if game["status"] == "lobby":
        text = "🐍 <b>لابی بازی مار و پله</b> 🪜\n\n"
        text += f"👥 بازیکنان ({len(game['players'])}/4):\n"
        for p in game["players"]:
            text += f"{p['icon']} {p['name']}\n"
        text += "\n👇 برای ورود دکمه زیر را بزنید. میزبان می‌تواند بازی را شروع کند."
        return text
    else:
        current = game["players"][game["turn_index"]]
        text = f"🎲 <b>نوبت:</b> {current['icon']} {current['name']} (⏳ {TURN_TIMEOUT} ثانیه)\n"
        
        if game.get("last_action"):
            text += f"📢 <b>رویداد:</b> <i>{game['last_action']}</i>\n\n"
        else:
            text += "\n"
            
        text += "🗺 <b>نقشه بازی:</b>\n"
        text += _draw_text_board(game["players"])
        
        text += "\n\n📊 <b>آمار زنده:</b>\n"
        for idx, p in enumerate(game["players"]):
            light = "🟢" if idx == game["turn_index"] else "🔴"
            pos = "🏁 <b>برنده!</b>" if p["pos"] == 100 else f"خانه <b>{p['pos']}</b>"
            text += f"{light} {p['icon']} {p['name']}: {pos}\n"
            
        return text

def _get_lobby_keyboard(game: dict) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🎮 ورود به بازی", callback_data="snake_join")],
    ]
    if len(game["players"]) >= 2:
        kb.append([InlineKeyboardButton("🚀 شروع بازی (میزبان)", callback_data="snake_start")])
    return InlineKeyboardMarkup(kb)

def _get_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 پرتاب تاس", callback_data="snake_roll")],
        [
            InlineKeyboardButton("🔄 آپدیت", callback_data="snake_refresh"),
            InlineKeyboardButton("🎮 ورود جدید", callback_data="snake_join"),
            InlineKeyboardButton("❌ انصراف", callback_data="snake_surrender")
        ]
    ])

async def auto_roll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """تابع اجرای خودکار تاس در صورت تاخیر بازیکن"""
    job = context.job
    chat_id = job.chat_id
    game = ACTIVE_GAMES.get(chat_id)
    
    if not game or game["status"] != "playing":
        return
        
    current_player = game["players"][game["turn_index"]]
    if job.data != current_player["id"]:
        return # نوبت عوض شده است
        
    # اجرای خودکار تاس
    await context.bot.send_message(chat_id=chat_id, text=f"⏰ زمان {current_player['name']} تموم شد! ربات به جای او تاس می‌ندازه...")
    await _process_roll(context, chat_id, current_player["id"], is_auto=True)

async def _process_roll(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, is_auto=False) -> None:
    """منطق اصلی پرتاب تاس و حرکت"""
    game = ACTIVE_GAMES.get(chat_id)
    if not game or game["status"] != "playing": return
    
    current_player = game["players"][game["turn_index"]]
    if current_player["id"] != user_id and not is_auto: return

    # حذف تایمر قبلی
    jobs = context.job_queue.get_jobs_by_name(f"snake_timer_{chat_id}")
    for job in jobs: job.schedule_removal()

    dice = random.randint(1, 6)
    old_pos = current_player["pos"]
    target_pos = old_pos + dice
    
    action = f"{current_player['icon']} {current_player['name']} تاس {dice} آورد. "
    
    if target_pos > 100:
        action += "اما از ۱۰۰ رد شد و ماند."
    else:
        action += f"به {target_pos} رفت. "
        
        # 💥 سیستم ضربه زدن (برخورد با بازیکن دیگر)
        for p in game["players"]:
            if p["id"] != current_player["id"] and p["pos"] == target_pos:
                p["pos"] = 0
                action += f"💥 {current_player['name']} زد به {p['name']} و فرستادش خانه ۱! "
        
        current_player["pos"] = target_pos
        
        # 🐍 مار و 🪜 پله
        if target_pos in LADDERS:
            action += f"🪜 پله! رفت به {LADDERS[target_pos]}."
            current_player["pos"] = LADDERS[target_pos]
        elif target_pos in SNAKES:
            action += f"🐍 مار! افتاد به {SNAKES[target_pos]}."
            current_player["pos"] = SNAKES[target_pos]

    game["last_action"] = action
    
    # بررسی برد
    if current_player["pos"] == 100:
        game["status"] = "finished"
        game["last_action"] = f"🏆 {current_player['icon']} <b>{current_player['name']} برنده شد!</b> 🎉"
        await context.bot.send_message(chat_id=chat_id, text=_get_game_text(game), parse_mode="HTML")
        del ACTIVE_GAMES[chat_id]
        return

    # تغییر نوبت (اگر ۶ آورده بود دوباره خودش)
    if dice != 6:
        game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
    else:
        game["last_action"] += " (چون ۶ آورد، دوباره می‌ندازه!)"

    next_player = game["players"][game["turn_index"]]
    
    # ارسال پیام جدید آپدیت شده
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=_get_game_text(game),
        parse_mode="HTML",
        reply_markup=_get_game_keyboard()
    )
    game["message_id"] = msg.message_id

    # تنظیم تایمر جدید برای نفر بعدی
    context.job_queue.run_once(
        auto_roll_job,
        when=TURN_TIMEOUT,
        chat_id=chat_id,
        data=next_player["id"],
        name=f"snake_timer_{chat_id}"
    )

async def cmd_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in ACTIVE_GAMES:
        await update.message.reply_text("⚠️ یک بازی در جریان است!")
        return

    ACTIVE_GAMES[chat_id] = {
        "status": "lobby",
        "host_id": update.effective_user.id,
        "players": [{"id": update.effective_user.id, "name": update.effective_user.first_name, "pos": 0, "icon": PLAYER_ICONS[0]}],
        "turn_index": 0,
        "last_action": None,
    }

    msg = await update.message.reply_text(
        _get_game_text(ACTIVE_GAMES[chat_id]),
        parse_mode="HTML",
        reply_markup=_get_lobby_keyboard(ACTIVE_GAMES[chat_id])
    )
    ACTIVE_GAMES[chat_id]["message_id"] = msg.message_id

async def handle_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id not in ACTIVE_GAMES:
        await query.answer("بازی تمام شده است.", show_alert=True); return

    game = ACTIVE_GAMES[chat_id]

    # 🔄 دکمه آپدیت (آوردن به پایین)
    if query.data == "snake_refresh":
        await query.answer("بازی آپدیت شد!")
        try: await query.message.delete()
        except: pass
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text=_get_game_text(game),
            parse_mode="HTML",
            reply_markup=_get_game_keyboard() if game["status"] == "playing" else _get_lobby_keyboard(game)
        )
        game["message_id"] = msg.message_id
        return

    # 🎮 ورود (چه در لابی چه وسط بازی)
    if query.data == "snake_join":
        if any(p["id"] == user.id for p in game["players"]):
            await query.answer("شما قبلاً وارد شده‌اید.", show_alert=True); return
        if len(game["players"]) >= 4:
            await query.answer("ظرفیت (۴ نفر) پر است.", show_alert=True); return

        game["players"].append({"id": user.id, "name": user.first_name, "pos": 0, "icon": PLAYER_ICONS[len(game["players"])]})
        await query.answer("✅ وارد شدید!")
        
        if game["status"] == "lobby":
            await query.edit_message_text(_get_game_text(game), parse_mode="HTML", reply_markup=_get_lobby_keyboard(game))
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"{PLAYER_ICONS[len(game['players'])-1]} {user.first_name} وسط بازی وارد شد! برای دیدن بازی روی دکمه آپدیت بزنید.", reply_markup=_get_game_keyboard())
        return

    # 🚀 شروع بازی
    if query.data == "snake_start":
        if user.id != game["host_id"]:
            await query.answer("فقط میزبان!", show_alert=True); return
        if len(game["players"]) < 2:
            await query.answer("حداقل ۲ نفر.", show_alert=True); return

        game["status"] = "playing"
        game["turn_index"] = 0
        game["last_action"] = "بازی شروع شد! نوبت به پرتاب تاس است."
        
        await query.message.delete()
        msg = await context.bot.send_message(chat_id=chat_id, text=_get_game_text(game), parse_mode="HTML", reply_markup=_get_game_keyboard())
        game["message_id"] = msg.message_id
        
        # استارت تایمر اول
        next_p = game["players"][0]
        context.job_queue.run_once(auto_roll_job, when=TURN_TIMEOUT, chat_id=chat_id, data=next_p["id"], name=f"snake_timer_{chat_id}")
        return

    # ❌ انصراف
    if query.data == "snake_surrender":
        p_idx = next((i for i, p in enumerate(game["players"]) if p["id"] == user.id), None)
        if p_idx is not None:
            surrendered_player = game["players"].pop(p_idx)
            await query.answer("شما از بازی خارج شدید.")
            
            if len(game["players"]) < 2:
                del ACTIVE_GAMES[chat_id]
                await query.edit_message_text(f"🏳️ {surrendered_player['name']} انصراف داد. بازیکن کافی نماند، بازی لغو شد.")
                return

            if game["turn_index"] >= len(game["players"]):
                game["turn_index"] = 0
                
            await context.bot.send_message(chat_id=chat_id, text=f"🏳️ {surrendered_player['name']} انصراف داد!", reply_markup=_get_game_keyboard())
        return

    # 🎲 پرتاب تاس
    if query.data == "snake_roll":
        if game["status"] != "playing":
            await query.answer("بازی فعال نیست.", show_alert=True); return
        
        current = game["players"][game["turn_index"]]
        if user.id != current["id"]:
            await query.answer(f"نوبت شما نیست! نوبت {current['name']} است.", show_alert=True); return

        await query.answer("در حال حرکت... 🎲")
        try: await query.message.delete()
        except: pass
        
        await _process_roll(context, chat_id, user.id, is_auto=False)
        return
