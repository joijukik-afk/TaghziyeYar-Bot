"""بازی مار و پله فوق حرفه‌ای، متنی و زنده (با قابلیت بازی با ربات)"""

import random
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ChatType

logger = logging.getLogger(__name__)

LADDERS = {2: 38, 7: 14, 8: 31, 15: 26, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 78: 98}
SNAKES = {16: 6, 46: 25, 49: 11, 62: 19, 64: 60, 74: 53, 89: 68, 92: 88, 95: 75, 99: 80}

ACTIVE_GAMES = {}
PLAYER_ICONS = ["🦊", "🐼", "🦁", "🐸"] 
TURN_TIMEOUT = 30 

def _draw_text_board(players: list) -> str:
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
            if val: line += f"[ {val} ]"
            else: line += f"[{pos:02d} ]" if pos < 100 else "[100]"
        lines.append(line)
    lines.append("</pre>")
    return "\n".join(lines)

def _get_game_text(game: dict) -> str:
    if game["status"] == "lobby":
        text = "🐍 <b>لابی بازی مار و پله</b> 🪜\n\n"
        text += f"👥 بازیکنان ({len(game['players'])}/4):\n"
        for p in game["players"]: text += f"{p['icon']} {p['name']}\n"
        text += "\n👇 برای ورود دکمه زیر را بزنید یا با ربات بازی کنید."
        return text
    
    current = game["players"][game["turn_index"]]
    text = f"🎲 <b>نوبت:</b> {current['icon']} {current['name']} (⏳ {TURN_TIMEOUT} ثانیه)\n"
    if game.get("last_action"): text += f"📢 <b>رویداد:</b> <i>{game['last_action']}</i>\n\n"
    else: text += "\n"
    
    text += "🗺 <b>نقشه بازی:</b>\n" + _draw_text_board(game["players"])
    text += "\n\n📊 <b>آمار زنده:</b>\n"
    for idx, p in enumerate(game["players"]):
        light = "🟢" if idx == game["turn_index"] else "🔴"
        pos = "🏁 <b>برنده!</b>" if p["pos"] == 100 else f"خانه <b>{p['pos']}</b>"
        text += f"{light} {p['icon']} {p['name']}: {pos}\n"
    return text

def _get_lobby_keyboard(game: dict) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🎮 ورود به بازی", callback_data="snake_join")],
        [InlineKeyboardButton("🤖 بازی با ربات", callback_data="snake_play_bot")] # 👈 دکمه بازی با ربات
    ]
    if len(game["players"]) >= 2:
        kb.append([InlineKeyboardButton("🚀 شروع بازی (میزبان)", callback_data="snake_start")])
    return InlineKeyboardMarkup(kb)

def _get_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 پرتاب تاس", callback_data="snake_roll")],
        [InlineKeyboardButton("🔄 آپدیت", callback_data="snake_refresh"), InlineKeyboardButton("🎮 ورود جدید", callback_data="snake_join"), InlineKeyboardButton("❌ انصراف", callback_data="snake_surrender")]
    ])

async def auto_roll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """اجرای خودکار تاس برای بازیکن انسانی در صورت تاخیر"""
    job = context.job
    game = ACTIVE_GAMES.get(job.chat_id)
    if not game or game["status"] != "playing": return
    current_player = game["players"][game["turn_index"]]
    if job.data != current_player["id"] or current_player["id"] == -1: return
    
    await context.bot.send_message(chat_id=job.chat_id, text=f"⏰ زمان {current_player['name']} تموم شد! ربات براش تاس می‌ندازه...")
    await _process_roll(context, job.chat_id, current_player["id"], is_auto=True)

async def bot_roll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """اجرای تاس توسط ربات (بازیکن هوش مصنوعی)"""
    job = context.job
    game = ACTIVE_GAMES.get(job.chat_id)
    if not game or game["status"] != "playing": return
    current_player = game["players"][game["turn_index"]]
    if current_player["id"] != -1: return # نوبت ربات نیست
    
    await _process_roll(context, job.chat_id, -1, is_auto=True)

async def _process_roll(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, is_auto=False) -> None:
    game = ACTIVE_GAMES.get(chat_id)
    if not game or game["status"] != "playing": return
    
    current_player = game["players"][game["turn_index"]]
    if current_player["id"] != user_id and not is_auto: return

    # حذف تایمرهای قبلی (چه انسانی چه ربات)
    for job in context.job_queue.get_jobs_by_name(f"snake_timer_{chat_id}"): job.schedule_removal()
    for job in context.job_queue.get_jobs_by_name(f"snake_bot_timer_{chat_id}"): job.schedule_removal()

    dice = random.randint(1, 6)
    old_pos = current_player["pos"]
    target_pos = old_pos + dice
    action = f"{current_player['icon']} {current_player['name']} تاس {dice} آورد. "
    
    if target_pos > 100:
        action += "اما از ۱۰۰ رد شد و ماند."
    else:
        action += f"به {target_pos} رفت. "
        
        for p in game["players"]:
            if p["id"] != current_player["id"] and p["pos"] == target_pos:
                p["pos"] = 0
                action += f"💥 {current_player['name']} زد به {p['name']} و فرستادش خانه ۱! "
        
        current_player["pos"] = target_pos
        
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

    # تغییر نوبت
    if dice != 6:
        game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
    else:
        game["last_action"] += " (چون ۶ آورد، دوباره می‌ندازه!)"

    next_player = game["players"][game["turn_index"]]
    
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=_get_game_text(game),
        parse_mode="HTML",
        reply_markup=_get_game_keyboard()
    )
    game["message_id"] = msg.message_id

    # زمان‌بندی برای نوبت بعدی
    if next_player["id"] == -1:
        # اگر نوبت ربات است، ۲ ثانیه بعد خودش تاس می‌ندازه
        context.job_queue.run_once(bot_roll_job, when=2.0, chat_id=chat_id, name=f"snake_bot_timer_{chat_id}")
    else:
        # اگر نوبت انسان است، ۳۰ ثانیه صبر می‌کنیم
        context.job_queue.run_once(auto_roll_job, when=TURN_TIMEOUT, chat_id=chat_id, data=next_player["id"], name=f"snake_timer_{chat_id}")

async def cmd_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in ACTIVE_GAMES: await update.message.reply_text("⚠️ یک بازی در جریان است!"); return
    ACTIVE_GAMES[chat_id] = {"status": "lobby", "host_id": update.effective_user.id, "players": [{"id": update.effective_user.id, "name": update.effective_user.first_name, "pos": 0, "icon": PLAYER_ICONS[0]}], "turn_index": 0, "last_action": None}
    msg = await update.message.reply_text(_get_game_text(ACTIVE_GAMES[chat_id]), parse_mode="HTML", reply_markup=_get_lobby_keyboard(ACTIVE_GAMES[chat_id]))
    ACTIVE_GAMES[chat_id]["message_id"] = msg.message_id

async def handle_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query; chat_id = update.effective_chat.id; user = update.effective_user
    if chat_id not in ACTIVE_GAMES: await query.answer("بازی تمام شده است.", show_alert=True); return
    game = ACTIVE_GAMES[chat_id]

    if query.data == "snake_refresh":
        await query.answer("بازی آپدیت شد!")
        try: await query.message.delete()
        except: pass
        msg = await context.bot.send_message(chat_id=chat_id, text=_get_game_text(game), parse_mode="HTML", reply_markup=_get_game_keyboard() if game["status"] == "playing" else _get_lobby_keyboard(game))
        game["message_id"] = msg.message_id; return

    if query.data == "snake_join":
        if any(p["id"] == user.id for p in game["players"]): await query.answer("شما قبلاً وارد شده‌اید.", show_alert=True); return
        if len(game["players"]) >= 4: await query.answer("ظرفیت پر است.", show_alert=True); return
        game["players"].append({"id": user.id, "name": user.first_name, "pos": 0, "icon": PLAYER_ICONS[len(game["players"])]})
        await query.answer("✅ وارد شدید!")
        if game["status"] == "lobby": await query.edit_message_text(_get_game_text(game), parse_mode="HTML", reply_markup=_get_lobby_keyboard(game))
        else: await context.bot.send_message(chat_id=chat_id, text=f"{PLAYER_ICONS[len(game['players'])-1]} {user.first_name} وسط بازی وارد شد! روی آپدیت بزنید.", reply_markup=_get_game_keyboard())
        return

    # 🤖 بازی با ربات
    if query.data == "snake_play_bot":
        if game["status"] != "lobby": await query.answer("بازی شروع شده است!", show_alert=True); return
        if any(p["id"] == -1 for p in game["players"]): await query.answer("ربات از قبل در بازی است.", show_alert=True); return
        
        # اضافه کردن ربات به بازی
        game["players"].append({"id": -1, "name": "ربات", "pos": 0, "icon": "🤖"})
        game["status"] = "playing"
        game["turn_index"] = 0
        game["last_action"] = "بازی با ربات شروع شد! نوبت شماست."
        
        await query.message.delete()
        msg = await context.bot.send_message(chat_id=chat_id, text=_get_game_text(game), parse_mode="HTML", reply_markup=_get_game_keyboard())
        game["message_id"] = msg.message_id
        context.job_queue.run_once(auto_roll_job, when=TURN_TIMEOUT, chat_id=chat_id, data=game["players"][0]["id"], name=f"snake_timer_{chat_id}")
        return

    if query.data == "snake_start":
        if user.id != game["host_id"] or len(game["players"]) < 2: await query.answer("شرایط شروع فراهم نیست.", show_alert=True); return
        game["status"] = "playing"; game["turn_index"] = 0; game["last_action"] = "بازی شروع شد!"
        await query.message.delete()
        msg = await context.bot.send_message(chat_id=chat_id, text=_get_game_text(game), parse_mode="HTML", reply_markup=_get_game_keyboard())
        game["message_id"] = msg.message_id
        
        next_p = game["players"][0]
        if next_p["id"] == -1: context.job_queue.run_once(bot_roll_job, when=2.0, chat_id=chat_id, name=f"snake_bot_timer_{chat_id}")
        else: context.job_queue.run_once(auto_roll_job, when=TURN_TIMEOUT, chat_id=chat_id, data=next_p["id"], name=f"snake_timer_{chat_id}")
        return

    if query.data == "snake_surrender":
        p_idx = next((i for i, p in enumerate(game["players"]) if p["id"] == user.id), None)
        if p_idx is not None:
            s_p = game["players"].pop(p_idx); await query.answer("شما خارج شدید.")
            if len(game["players"]) < 2: del ACTIVE_GAMES[chat_id]; await query.edit_message_text(f"🏳️ {s_p['name']} انصراف داد. بازی لغو شد."); return
            if game["turn_index"] >= len(game["players"]): game["turn_index"] = 0
            
            await context.bot.send_message(chat_id=chat_id, text=f"🏳️ {s_p['name']} انصراف داد!", reply_markup=_get_game_keyboard())
            
            # بررسی اینکه نوبت بعدی با کی هست
            next_p = game["players"][game["turn_index"]]
            if next_p["id"] == -1: context.job_queue.run_once(bot_roll_job, when=2.0, chat_id=chat_id, name=f"snake_bot_timer_{chat_id}")
            else: context.job_queue.run_once(auto_roll_job, when=TURN_TIMEOUT, chat_id=chat_id, data=next_p["id"], name=f"snake_timer_{chat_id}")
        return

    if query.data == "snake_roll":
        if game["status"] != "playing" or user.id != game["players"][game["turn_index"]]["id"]: await query.answer("نوبت شما نیست!", show_alert=True); return
        await query.answer("در حال حرکت...")
        try: await query.message.delete()
        except: pass
        await _process_roll(context, chat_id, user.id, is_auto=False)
