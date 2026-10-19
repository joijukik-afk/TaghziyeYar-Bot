"""بازی مار و پله حرفه‌ای با نقشه شطرنجی و انیمیشن درون‌پیام"""

import random
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ChatType

logger = logging.getLogger(__name__)

# نقشه استاندارد مارها و پله‌ها
LADDERS = {2: 38, 7: 14, 8: 31, 15: 26, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 78: 98}
SNAKES = {16: 6, 46: 25, 49: 11, 62: 19, 64: 60, 74: 53, 89: 68, 92: 88, 95: 75, 99: 80}

ACTIVE_GAMES = {}
PLAYER_ICONS = ["🦊", "🐼", "🦁", "🐸"] 
TURN_TIMEOUT = 60 

def _draw_text_board(players: list) -> str:
    """ساخت نقشه ۱۰x۱۰ با استفاده از HTML و ایموجی‌های شطرنجی"""
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
                # خانه‌های دارای مار، پله یا بازیکن
                line += f"[{val} ]"
            else:
                # خانه‌های خالی با پس‌زمینه شطرنجی
                bg = "⬛" if (row + col) % 2 == 0 else "⬜"
                if pos == 100:
                    line += f"[{bg}🏁]" # خانه آخر
                else:
                    line += f"[{bg}{pos:02d}]"
        lines.append(line)
    lines.append("</pre>")
    return "\n".join(lines)

def _get_game_text(game: dict) -> str:
    """ساخت متن وضعیت بازی"""
    if game["status"] == "lobby":
        text = "🐍 <b>لابی بازی مار و پله</b> 🪜\n\n"
        text += f"👥 بازیکنان ({len(game['players'])}/4):\n"
        for p in game["players"]: text += f"{p['icon']} {p['name']}\n"
        text += "\n👇 برای ورود روی دکمه زیر کلیک کنید."
        return text
    
    current = game["players"][game["turn_index"]]
    text = f"🎲 <b>نوبت:</b> {current['icon']} {current['name']}\n"
    if game.get("last_action"): text += f"📢 <i>{game['last_action']}</i>\n\n"
    else: text += "\n"
    
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
        [InlineKeyboardButton("🤖 بازی با ربات", callback_data="snake_play_bot")]
    ]
    if len(game["players"]) >= 2:
        kb.append([InlineKeyboardButton("🚀 شروع بازی", callback_data="snake_start")])
    return InlineKeyboardMarkup(kb)

def _get_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 پرتاب تاس", callback_data="snake_roll")],
        [InlineKeyboardButton("❌ انصراف", callback_data="snake_surrender")]
    ])

async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """یادآوری به بازیکن (بدون تاس خودکار)"""
    job = context.job
    game = ACTIVE_GAMES.get(job.chat_id)
    if game and game["status"] == "playing":
        current = game["players"][game["turn_index"]]
        if current["id"] == job.data:
            await context.bot.send_message(chat_id=job.chat_id, text=f"⏳ {current['name']} عزیز، منتظر تاس شما هستیم...")

async def _process_roll(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, user_id: int) -> None:
    """منطق اصلی پرتاب تاس و حرکت با انیمیشن درون‌پیام"""
    game = ACTIVE_GAMES.get(chat_id)
    if not game or game["status"] != "playing": return
    
    current_player = game["players"][game["turn_index"]]
    if current_player["id"] != user_id: return

    for job in context.job_queue.get_jobs_by_name(f"snake_reminder_{chat_id}"): job.schedule_removal()

    dice = random.randint(1, 6)
    old_pos = current_player["pos"]
    target_pos = old_pos + dice
    action = f"{current_player['icon']} {current_player['name']} تاس {dice} آورد. "
    
    if target_pos > 100:
        action += "اما از ۱۰۰ رد شد و ماند."
    else:
        # 🏃‍♂️ انیمیشن حرکت قدم به قدم (رفرش درون‌مپ)
        for step in range(old_pos + 1, target_pos + 1):
            current_player["pos"] = step
            game["last_action"] = f"{current_player['name']} در حال حرکت... ({step})"
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id,
                    text=_get_game_text(game), parse_mode="HTML",
                    reply_markup=_get_game_keyboard()
                )
                await asyncio.sleep(0.5) # تاخیر برای جلوگیری از اسپم
            except Exception: pass

        # 💥 بررسی برخورد با بازیکن دیگر
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
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=_get_game_text(game), parse_mode="HTML", reply_markup=None)
        del ACTIVE_GAMES[chat_id]
        return

    # تغییر نوبت
    if dice != 6: game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
    else: game["last_action"] += " (چون ۶ آورد، دوباره می‌ندازه!)"

    next_player = game["players"][game["turn_index"]]
    
    # رفرش نهایی
    await context.bot.edit_message_text(
        chat_id=chat_id, message_id=message_id,
        text=_get_game_text(game), parse_mode="HTML",
        reply_markup=_get_game_keyboard()
    )

    # تنظیم یادآوری برای نفر بعدی
    context.job_queue.run_once(reminder_job, when=TURN_TIMEOUT, chat_id=chat_id, data=next_player["id"], name=f"snake_reminder_{chat_id}")

async def cmd_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in ACTIVE_GAMES: await update.message.reply_text("⚠️ یک بازی در جریان است!"); return
    ACTIVE_GAMES[chat_id] = {"status": "lobby", "host_id": update.effective_user.id, "players": [{"id": update.effective_user.id, "name": update.effective_user.first_name, "pos": 0, "icon": PLAYER_ICONS[0]}], "turn_index": 0, "last_action": None, "message_id": None}
    msg = await update.message.reply_text(_get_game_text(ACTIVE_GAMES[chat_id]), parse_mode="HTML", reply_markup=_get_lobby_keyboard(ACTIVE_GAMES[chat_id]))
    ACTIVE_GAMES[chat_id]["message_id"] = msg.message_id

async def handle_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; chat_id = update.effective_chat.id; user = update.effective_user
    if chat_id not in ACTIVE_GAMES: await query.answer("بازی تمام شده است.", show_alert=True); return
    game = ACTIVE_GAMES[chat_id]; msg_id = game["message_id"]

    if query.data == "snake_join":
        if any(p["id"] == user.id for p in game["players"]): await query.answer("شما قبلاً وارد شده‌اید.", show_alert=True); return
        if len(game["players"]) >= 4: await query.answer("ظرفیت پر است.", show_alert=True); return
        game["players"].append({"id": user.id, "name": user.first_name, "pos": 0, "icon": PLAYER_ICONS[len(game["players"])]})
        await query.answer("✅ وارد شدید!")
        await query.edit_message_text(_get_game_text(game), parse_mode="HTML", reply_markup=_get_lobby_keyboard(game))
        return

    if query.data == "snake_play_bot":
        if game["status"] != "lobby": await query.answer("بازی شروع شده است!", show_alert=True); return
        game["players"].append({"id": -1, "name": "ربات", "pos": 0, "icon": "🤖"})
        game["status"] = "playing"; game["turn_index"] = 0; game["last_action"] = "بازی با ربات شروع شد! نوبت شماست."
        await query.answer("بازی شروع شد!")
        await query.edit_message_text(_get_game_text(game), parse_mode="HTML", reply_markup=_get_game_keyboard())
        context.job_queue.run_once(reminder_job, when=TURN_TIMEOUT, chat_id=chat_id, data=game["players"][0]["id"], name=f"snake_reminder_{chat_id}")
        return

    if query.data == "snake_start":
        if user.id != game["host_id"] or len(game["players"]) < 2: await query.answer("شرایط شروع فراهم نیست.", show_alert=True); return
        game["status"] = "playing"; game["turn_index"] = 0; game["last_action"] = "بازی شروع شد!"
        await query.answer("بازی شروع شد!")
        await query.edit_message_text(_get_game_text(game), parse_mode="HTML", reply_markup=_get_game_keyboard())
        context.job_queue.run_once(reminder_job, when=TURN_TIMEOUT, chat_id=chat_id, data=game["players"][0]["id"], name=f"snake_reminder_{chat_id}")
        return

    if query.data == "snake_surrender":
        p_idx = next((i for i, p in enumerate(game["players"]) if p["id"] == user.id), None)
        if p_idx is not None:
            s_p = game["players"].pop(p_idx); await query.answer("شما خارج شدید.")
            if len(game["players"]) < 2: del ACTIVE_GAMES[chat_id]; await query.edit_message_text(f"🏳️ {s_p['name']} انصراف داد. بازی لغو شد."); return
            if game["turn_index"] >= len(game["players"]): game["turn_index"] = 0
            await query.edit_message_text(_get_game_text(game), parse_mode="HTML", reply_markup=_get_game_keyboard())
        return

    if query.data == "snake_roll":
        if game["status"] != "playing" or user.id != game["players"][game["turn_index"]]["id"]:
            await query.answer("نوبت شما نیست!", show_alert=True); return
        
        await query.answer("در حال حرکت...")
        await _process_roll(context, chat_id, msg_id, user.id)
        return
