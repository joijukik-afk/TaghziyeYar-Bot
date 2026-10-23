"""بازی حرفه‌ای مار و پله ۱۰۰ خانه‌ای برای تلگرام (گروهی و تک‌نفره)"""

import random
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, RetryAfter, TimedOut

logger = logging.getLogger(__name__)

# --- تنظیمات نقشه بازی ---
LADDERS = {1: 38, 4: 14, 9: 31, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 80: 100}
SNAKES = {16: 6, 47: 26, 49: 11, 56: 53, 62: 19, 64: 60, 87: 24, 93: 73, 95: 75, 98: 78}
DRAGONS = {20: 5, 40: 15, 70: 35, 90: 55}
LUCK = {10: 5, 35: 10, 60: 15, 85: 10}
MISFORTUNE = {30: -5, 50: -10, 75: -5, 97: -10}

MAX_POS = 100
ACTIVE_GAMES = {}
PLAYER_ICONS = ["🦊", "🐼", "🦁", "🐸"]
TURN_TIMEOUT = 40  # زمان نوبت هر بازیکن (ثانیه)

# قفل‌های همزمانی برای جلوگیری از تداخل
game_locks = {}

def _get_identifier(user) -> str:
    return f"@{user.username}" if user.username else user.first_name

def _draw_map(players: list) -> str:
    """رسم نقشه با فاصله‌گذاری استاندارد"""
    cells = {}
    for start in LADDERS: cells[start] = "🪜"
    for start in SNAKES: cells[start] = "🐍"
    for start in DRAGONS: cells[start] = "🐉"
    for start in LUCK: cells[start] = "🎁"
    for start in MISFORTUNE: cells[start] = "⚡️"
    
    for p in players:
        if p["pos"] > 0: 
            cells[p["pos"]] = p["icon"]

    lines = []
    for row in range(10, 0, -1):
        line = ""
        cols = range(1, 11) if row % 2 != 0 else range(10, 0, -1)
        for col in cols:
            pos = (row - 1) * 10 + col
            val = cells.get(pos)
            if val: 
                line += f"{val:^4}"
            else: 
                line += f"{pos:^4}" if pos < 100 else " 100"
        lines.append(line)
    return f"<pre>{chr(10).join(lines)}</pre>"

def _get_game_ui(game: dict) -> str:
    if game["status"] == "lobby":
        text = "🐍 <b>لابی بازی مار و پله (۱۰۰ خانه)</b> 🪜🐉\n\n"
        text += f"👥 بازیکنان ({len(game['players'])}/4):\n"
        for p in game["players"]: text += f"👤 {p['icon']} {p['name']}\n"
        text += "\n👇 برای ورود کلیک کنید. (برای شروع بازی باید تاس ۶ بیاورید!)"
        return text
    
    current = game["players"][game["turn_index"]]
    if current["id"] == -1: header = "🤖 <b>نوبت ربات است...</b>"
    else:
        dice_text = f" | 🎲 {game['last_dice']}" if game.get('last_dice') else ""
        header = f"🎲 <b>نوبت:</b> {current['icon']} {current['name']}{dice_text}"

    map_text = f"\n🗺 <b>نقشه (🪜 پله | 🐍 مار | 🐉 اژدها | 🎁 شانس | ⚡️ صاعقه):</b>\n"
    map_text += _draw_map(game["players"]) + "\n"

    stats = "\n📊 <b>آمار:</b>\n"
    for idx, p in enumerate(game["players"]):
        circle = "🟢" if idx == game["turn_index"] else "⚪"
        if p["pos"] == 0: pos_text = "⏳ منتظر ۶"
        elif p["pos"] == MAX_POS: pos_text = "🏆 برنده"
        else: pos_text = f"خانه {p['pos']:02d}"
        stats += f"{circle} {p['icon']} {p['name']}: {pos_text}\n"
        
    events = f"\n📢 <i>{game.get('last_action', '')}</i>"
    return f"{header}{map_text}{stats}{events}"

def _get_lobby_keyboard(game: dict) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(f"🎮 ورود به بازی ({len(game['players'])}/4)", callback_data="snake_join")],
        [InlineKeyboardButton("🤖 بازی با ربات", callback_data="snake_play_bot")]
    ]
    if len(game["players"]) >= 2: 
        kb.append([InlineKeyboardButton("🚀 شروع بازی", callback_data="snake_start")])
    kb.append([InlineKeyboardButton("📜 قوانین", callback_data="snake_rules")])
    return InlineKeyboardMarkup(kb)

def _get_game_keyboard(game: dict, is_rolling: bool = False) -> InlineKeyboardMarkup:
    if is_rolling:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⏳ در حال حرکت...", callback_data="snake_wait")]])
    
    kb = []
    if len(game["players"]) < 4: 
        kb.append([InlineKeyboardButton(f"🎮 ورود به بازی ({len(game['players'])}/4)", callback_data="snake_join")])
    kb.append([InlineKeyboardButton("🎲 پرتاب تاس", callback_data="snake_roll")])
    kb.append([InlineKeyboardButton("🔄 آوردن بازی به پایین", callback_data="snake_bump")])
    kb.append([InlineKeyboardButton("📜 قوانین", callback_data="snake_rules")])
    kb.append([InlineKeyboardButton("❌ انصراف", callback_data="snake_surrender")])
    return InlineKeyboardMarkup(kb)

async def _safe_edit(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int, text: str, reply_markup=None, parse_mode="HTML"):
    """ویرایش امن پیام با مدیریت خطاهای تلگرام"""
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=text,
            parse_mode=parse_mode, reply_markup=reply_markup
        )
    except BadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning("Edit failed (BadRequest): %s", e)
    except RetryAfter as e:
        logger.warning("Flood control: retry after %s seconds", e.retry_after)
        await asyncio.sleep(e.retry_after)
    except TimedOut:
        logger.warning("Request timed out, skipping edit.")
    except Exception as e:
        logger.error("Unexpected edit error: %s", e)

async def _auto_roll_timeout(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job; game = ACTIVE_GAMES.get(job.chat_id)
    if not game or game["status"] != "playing" or game.get("is_rolling"): return
    current = game["players"][game["turn_index"]]
    if current["id"] == job.data:
        game["last_action"] = f"⏰ زمان {current['name']} تمام شد! ربات به جای او تاس می‌اندازد."
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

    # قفل کردن برای جلوگیری از کلیک همزمان
    if chat_id not in game_locks:
        game_locks[chat_id] = asyncio.Lock()
    
    async with game_locks[chat_id]:
        if game.get("is_rolling"): return
        game["is_rolling"] = True

        for job in context.job_queue.get_jobs_by_name(f"snake_timer_{chat_id}"): job.schedule_removal()
        for job in context.job_queue.get_jobs_by_name(f"snake_bot_{chat_id}"): job.schedule_removal()

        await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), _get_game_keyboard(game, True))

        dice = random.randint(1, 6)
        game["last_dice"] = dice
        old_pos = current["pos"]
        
        if old_pos == 0 and dice != 6:
            game["last_action"] = f"🔒 {current['name']} برای ورود باید ۶ بیاورد! (تاس: {dice})"
            await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), _get_game_keyboard(game, False))
            await asyncio.sleep(1.5)
        else:
            target_pos = old_pos + dice if old_pos != 0 else dice
            if target_pos > MAX_POS:
                target_pos = MAX_POS - (target_pos - MAX_POS)
                game["last_action"] = f"🔄 {current['name']} تاس {dice} آورد، از ۱۰۰ رد شد و برگشت به {target_pos}."
            else:
                game["last_action"] = f"➡️ {current['name']} تاس {dice} آورد و به خانه {target_pos} رفت."
            
            step_dir = 1 if target_pos > old_pos else -1
            # پرش انیمیشن برای شروع بازی
            start_pos = old_pos if old_pos > 0 else 0
            for step in range(start_pos + step_dir, target_pos + step_dir, step_dir):
                current["pos"] = step
                await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), _get_game_keyboard(game, True))
                await asyncio.sleep(0.4)

            # بررسی برخورد با بازیکنان دیگر
            for p in game["players"]:
                if p["id"] != current["id"] and p["pos"] == target_pos:
                    p["pos"] = 0
                    game["last_action"] = f"💥 {current['name']} زد به {p['name']} و فرستادش خانه ۱!"
                    await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), _get_game_keyboard(game, True))
                    await asyncio.sleep(1.5)

            # بررسی مار و پله و حوادث
            if target_pos in LADDERS:
                current["pos"] = LADDERS[target_pos]
                game["last_action"] = f"🪜 {current['name']} پله رفت! به خانه {current['pos']}."
            elif target_pos in SNAKES:
                current["pos"] = SNAKES[target_pos]
                game["last_action"] = f"🐍 {current['name']} مار خورد! به خانه {current['pos']}."
            elif target_pos in DRAGONS:
                current["pos"] = DRAGONS[target_pos]
                game["last_action"] = f"🐉 {current['name']} اژدها خورد! به خانه {current['pos']}."
            elif target_pos in LUCK:
                current["pos"] = min(MAX_POS, target_pos + LUCK[target_pos])
                game["last_action"] = f"🎁 {current['name']} جعبه شانس پیدا کرد! {LUCK[target_pos]} خانه جلو رفت."
            elif target_pos in MISFORTUNE:
                current["pos"] = max(0, target_pos + MISFORTUNE[target_pos])
                game["last_action"] = f"⚡️ {current['name']} صاعقه خورد! {abs(MISFORTUNE[target_pos])} خانه عقب افتاد."

            await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), _get_game_keyboard(game, True))
            await asyncio.sleep(1.2)

        game["is_rolling"] = False
        
        if current["pos"] == MAX_POS:
            game["status"] = "finished"
            game["last_action"] = f"🏆🎉 <b>تبریک بزرگ به {current['name']}!</b> 🎉🏆\n👑 با رسیدن به خانه ۱۰۰ قهرمان شد!"
            await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), None)
            if chat_id in ACTIVE_GAMES: del ACTIVE_GAMES[chat_id]
            if chat_id in game_locks: del game_locks[chat_id]
            return

        # تغییر نوبت
        if dice != 6: 
            game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
        else: 
            game["last_action"] += " (چون ۶ آورد، دوباره می‌ندازه!)"

        next_player = game["players"][game["turn_index"]]
        await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), _get_game_keyboard(game, False))

        # اعلان نوبت
        if next_player["id"] != -1:
            try:
                await context.bot.send_message(
                    chat_id=chat_id, 
                    text=f"🔔 {next_player['name']} نوبت شماست! (زمان: {TURN_TIMEOUT} ثانیه)",
                    reply_to_message_id=msg_id
                )
            except: pass
            context.job_queue.run_once(_auto_roll_timeout, when=TURN_TIMEOUT, chat_id=chat_id, data=next_player["id"], name=f"snake_timer_{chat_id}")
        else:
            context.job_queue.run_once(_bot_roll_job, when=1.5, chat_id=chat_id, name=f"snake_bot_{chat_id}")

async def cmd_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in ACTIVE_GAMES: 
        return await update.message.reply_text("⚠️ یک بازی در جریان است!")
    
    user_name = _get_identifier(update.effective_user)
    ACTIVE_GAMES[chat_id] = {
        "status": "lobby", "host_id": update.effective_user.id, 
        "players": [{"id": update.effective_user.id, "name": user_name, "pos": 0, "icon": PLAYER_ICONS[0]}],
        "turn_index": 0, "last_action": "بازی ساخته شد.", "is_rolling": False, "last_dice": None, "message_id": None
    }
    msg = await update.message.reply_text(_get_game_ui(ACTIVE_GAMES[chat_id]), parse_mode="HTML", reply_markup=_get_lobby_keyboard(ACTIVE_GAMES[chat_id]))
    ACTIVE_GAMES[chat_id]["message_id"] = msg.message_id

async def handle_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    
    await query.answer()
    
    chat_id = update.effective_chat.id; user = update.effective_user
    if chat_id not in ACTIVE_GAMES: 
        return await query.answer("بازی تمام شده است.", show_alert=True)
    game = ACTIVE_GAMES[chat_id]; msg_id = game["message_id"]

    if query.data == "snake_wait":
        return await query.answer("لطفاً صبر کنید...", show_alert=False)
        
    if query.data == "snake_rules":
        rules = (
            "📜 **قوانین بازی مار و پله:**\n\n"
            "1️⃣ برای شروع حرکت باید تاس **۶** بیاورید.\n"
            "2️⃣ اگر تاس ۶ بیاورید، یک نوبت دیگر هم می‌اندازید.\n"
            "3️⃣ اگر روی خونه بازیکن دیگه بیفتید، اون رو به خانه ۰ می‌فرستید (پرتش می‌کنید).\n"
            "4️⃣ 🪜 نردبان شما رو جلو می‌بره.\n"
            "5️⃣ 🐍 مار، 🐉 اژدها و ⚡️ صاعقه شما رو عقب می‌برن.\n"
            "6️⃣ 🎁 جعبه شانس شما رو جلو می‌بره.\n"
            "7️⃣ اگر از خانه ۱۰۰ رد بشید، به همون اندازه برمی‌گردید عقب.\n"
            "8️⃣ زمان هر نوبت ۴۰ ثانیه است، اگر تاس نندازید ربات خودش براتون می‌ندازه!\n\n"
            "🏆 اولین کسی که دقیقاً به خانه ۱۰۰ برسه، برنده است!"
        )
        return await query.answer(rules, show_alert=True)

    if query.data == "snake_bump":
        if not any(p["id"] == user.id for p in game["players"]): 
            return await query.answer("فقط بازیکنان!", show_alert=True)
        
        kb = _get_lobby_keyboard(game) if game["status"] == "lobby" else _get_game_keyboard(game, game.get("is_rolling"))
        new_msg = await context.bot.send_message(chat_id=chat_id, text=_get_game_ui(game), parse_mode="HTML", reply_markup=kb)
        game["message_id"] = new_msg.message_id
        return

    if query.data == "snake_join":
        if game.get("is_rolling"): return await query.answer("در حال حرکت!", show_alert=True)
        if any(p["id"] == user.id for p in game["players"]): return await query.answer("قبلاً وارد شدید.", show_alert=True)
        if len(game["players"]) >= 4: return await query.answer("ظرفیت پر است.", show_alert=True)
        
        user_name = _get_identifier(user)
        game["players"].append({"id": user.id, "name": user_name, "pos": 0, "icon": PLAYER_ICONS[len(game["players"])]})
        
        kb = _get_lobby_keyboard(game) if game["status"] == "lobby" else _get_game_keyboard(game)
        await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), kb)
        return

    if query.data == "snake_play_bot":
        if game["status"] != "lobby": return await query.answer("شروع شده است!", show_alert=True)
        game["players"].append({"id": -1, "name": "🤖 ربات", "pos": 0, "icon": "🤖"})
        game["status"] = "playing"; game["turn_index"] = 0; game["last_action"] = "بازی شروع شد! (منتظر ۶ باشید)"
        await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), _get_game_keyboard(game))
        context.job_queue.run_once(_auto_roll_timeout, when=TURN_TIMEOUT, chat_id=chat_id, data=game["players"][0]["id"], name=f"snake_timer_{chat_id}")
        return

    if query.data == "snake_start":
        if game.get("is_rolling"): return await query.answer("در حال حرکت!", show_alert=True)
        if user.id != game["host_id"] or len(game["players"]) < 2: 
            return await query.answer("شرایط شروع فراهم نیست. (حداقل ۲ نفر و فقط سازنده)", show_alert=True)
        game["status"] = "playing"; game["turn_index"] = 0; game["last_action"] = "بازی شروع شد! (منتظر ۶ باشید)"
        await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), _get_game_keyboard(game))
        context.job_queue.run_once(_auto_roll_timeout, when=TURN_TIMEOUT, chat_id=chat_id, data=game["players"][0]["id"], name=f"snake_timer_{chat_id}")
        return

    if query.data == "snake_surrender":
        if game.get("is_rolling"): return await query.answer("در حال حرکت!", show_alert=True)
        p_idx = next((i for i, p in enumerate(game["players"]) if p["id"] == user.id), None)
        if p_idx is not None:
            s_p = game["players"].pop(p_idx)
            if len(game["players"]) < 2: 
                if chat_id in ACTIVE_GAMES: del ACTIVE_GAMES[chat_id]
                if chat_id in game_locks: del game_locks[chat_id]
                await _safe_edit(context, chat_id, msg_id, f"🏳️ {s_p['name']} انصراف داد. بازی لغو شد.")
                return
            if game["turn_index"] >= len(game["players"]): game["turn_index"] = 0
            await _safe_edit(context, chat_id, msg_id, _get_game_ui(game), _get_game_keyboard(game))
        return

    if query.data == "snake_roll":
        if game.get("is_rolling"): return await query.answer("صبر کنید...", show_alert=True)
        if game["status"] != "playing" or user.id != game["players"][game["turn_index"]]["id"]: 
            return await query.answer("نوبت شما نیست!", show_alert=True)
        await _process_roll(context, chat_id, msg_id, user.id)
        return
