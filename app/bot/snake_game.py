"""بازی مار و پله - نسخه نهایی، فوق سریع و با صفحه قوانین اختصاصی"""

import random
import logging
import asyncio
import html
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, RetryAfter

logger = logging.getLogger(__name__)

# --- تنظیمات بازی ---
LADDERS = {1: 38, 4: 14, 9: 31, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 80: 100}
SNAKES = {16: 6, 47: 26, 49: 11, 56: 53, 62: 19, 64: 60, 87: 24, 93: 73, 95: 75, 98: 78}
DRAGONS = {20: 5, 40: 15, 70: 35, 90: 55}
LUCK = {10: 5, 35: 10, 60: 15, 85: 10}
MISFORTUNE = {30: -5, 50: -10, 75: -5, 97: -10}

MAX_POS = 100
TURN_TIMEOUT = 40  # زمان نوبت بازیکن (ثانیه)
PLAYER_ICONS = ["🦊", "🐼", "🦁", "🐸"]
BUMP_COOLDOWN = 5

ACTIVE_GAMES = {}
GAME_LOCKS = {}

def p_num(n: int) -> str:
    return str(n).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))

def _get_safe_name(user) -> str:
    return html.escape(user.first_name or "کاربر")

def _draw_board(players: list) -> str:
    cells = {}
    for pos in LADDERS: cells[pos] = "🪜"
    for pos in SNAKES: cells[pos] = "🐍"
    for pos in DRAGONS: cells[pos] = "🐉"
    for pos in LUCK: cells[pos] = "🎁"
    for pos in MISFORTUNE: cells[pos] = "⚡️"
    
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
    return f"<pre dir=\"ltr\">{chr(10).join(lines)}</pre>"

def _get_rules_text() -> str:
    return (
        "📜 <b>قوانین بازی مار و پله</b>\n\n"
        "🎲 برای شروع حرکت باید تاس <b>۶</b> بیاورید.\n"
        "🔄 اگر ۶ بیاورید، یک نوبت دیگر هم می‌اندازید.\n"
        "💥 اگر روی مهره حریف بیفتید، او به خانه ۱ برمی‌گردد.\n"
        "🪜 نردبان شما را جلو می‌برد.\n"
        "🐍 مار، 🐉 اژدها و ⚡️ صاعقه شما را عقب می‌برند.\n"
        "🎁 جعبه شانس شما را جلو می‌برد.\n"
        "🏆 اولین نفری که دقیقاً به خانه ۱۰۰ برسد، برنده است."
    )

def _get_ui(game: dict) -> str:
    if game.get("view") == "rules":
        return _get_rules_text()

    if game["status"] == "lobby":
        text = "🐍 <b>لابی بازی مار و پله</b> 🪜\n\n"
        text += f"👥 بازیکنان ({p_num(len(game['players']))}/۴):\n"
        for p in game["players"]: 
            text += f"👤 {p['icon']} {p['name']}\n"
        text += "\n👇 برای ورود کلیک کنید. (برای شروع باید ۶ بیاورید!)"
        return text
    
    current = game["players"][game["turn_index"]]
    if current["id"] == -1: 
        header = "🤖 <b>نوبت ربات است...</b>"
    else:
        mention = f"<a href='tg://user?id={current['id']}'>{current['name']}</a>"
        dice_str = f" | 🎲 {p_num(game['last_dice'])}" if game.get('last_dice') else ""
        header = f"🔔 <b>نوبت:</b> {current['icon']} {mention}{dice_str}"

    map_text = f"\n🗺 <b>نقشه:</b>\n{_draw_board(game['players'])}\n"

    stats = "\n📊 <b>آمار:</b>\n"
    for idx, p in enumerate(game["players"]):
        circle = "🟢" if idx == game["turn_index"] else "⚪"
        pos_text = "⏳ منتظر ۶" if p["pos"] == 0 else ("🏆 برنده" if p["pos"] == MAX_POS else f"خانه {p_num(p['pos'])}")
        stats += f"{circle} {p['icon']} {p['name']}: {pos_text}\n"
        
    events = f"\n📢 <i>{game.get('last_action', '')}</i>"
    return f"{header}{map_text}{stats}{events}"

def _get_lobby_kb(game: dict) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(f"🎮 ورود ({p_num(len(game['players']))}/۴)", callback_data="snake_join")],
        [InlineKeyboardButton("🤖 بازی با ربات", callback_data="snake_play_bot")],
        [InlineKeyboardButton("📜 قوانین", callback_data="snake_rules")]
    ]
    if len(game["players"]) >= 2: 
        kb.insert(1, [InlineKeyboardButton("🚀 شروع بازی", callback_data="snake_start")])
    kb.append([InlineKeyboardButton("🛑 بستن لابی", callback_data="snake_force_stop")])
    return InlineKeyboardMarkup(kb)

def _get_game_kb(game: dict, is_rolling: bool = False) -> InlineKeyboardMarkup:
    if game.get("view") == "rules":
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به بازی", callback_data="snake_back")]])

    if is_rolling:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⏳ در حال حرکت...", callback_data="snake_wait")]])
    
    kb = []
    if game["status"] == "playing":
        kb.append([InlineKeyboardButton("🎲 پرتاب تاس", callback_data="snake_roll")])
        kb.append([InlineKeyboardButton("⬇️ آوردن به پایین", callback_data="snake_bump")])
        kb.append([InlineKeyboardButton("📜 قوانین", callback_data="snake_rules")])
        kb.append([InlineKeyboardButton("❌ انصراف", callback_data="snake_surrender")])
        kb.append([InlineKeyboardButton("🛑 بستن اجباری", callback_data="snake_force_stop")])
    return InlineKeyboardMarkup(kb) if kb else None

async def _safe_edit(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int, text: str, kb=None):
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=text,
            parse_mode="HTML", reply_markup=kb
        )
    except BadRequest as e:
        err_str = str(e).lower()
        if "message is not modified" not in err_str:
            # اگر پیام پاک شده بود، پیام جدید می‌فرستیم
            if "message to edit not found" in err_str or "message_id_invalid" in err_str:
                if chat_id in ACTIVE_GAMES:
                    new_msg = await context.bot.send_message(chat_id, text=text, parse_mode="HTML", reply_markup=kb)
                    ACTIVE_GAMES[chat_id]["message_id"] = new_msg.message_id
            else:
                logger.warning(f"Edit failed: {e}")
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after)
    except Exception as e:
        logger.error(f"Edit error: {e}")

def _cleanup(chat_id: int):
    if chat_id in ACTIVE_GAMES:
        game = ACTIVE_GAMES[chat_id]
        if game.get("timer_task"): game["timer_task"].cancel()
        if game.get("bot_task"): game["bot_task"].cancel()
        del ACTIVE_GAMES[chat_id]
    if chat_id in GAME_LOCKS:
        del GAME_LOCKS[chat_id]

def _schedule_timer(context, chat_id: int, game: dict, player_id: int):
    if game.get("timer_task"): game["timer_task"].cancel()
    
    async def _timeout():
        try:
            await asyncio.sleep(TURN_TIMEOUT)
            if chat_id not in GAME_LOCKS: return
            async with GAME_LOCKS[chat_id]:
                g = ACTIVE_GAMES.get(chat_id)
                if not g or g["status"] != "playing" or g.get("is_rolling") or g.get("view") == "rules": return
                if g["turn_index"] >= len(g["players"]): return
                if g["players"][g["turn_index"]]["id"] == player_id:
                    g["last_action"] = f"⏰ زمان {g['players'][g['turn_index']]['name']} تمام شد!"
                    await _execute_roll(context, chat_id, g, player_id)
        except asyncio.CancelledError: pass
        except Exception as e: logger.error(f"Timer error: {e}")
    
    game["timer_task"] = asyncio.create_task(_timeout())

def _schedule_bot(context, chat_id: int, game: dict):
    if game.get("bot_task"): game["bot_task"].cancel()
    
    async def _bot_turn():
        try:
            await asyncio.sleep(0.5) # ربات سریع بازی میکنه (نیم ثانیه مکث)
            if chat_id not in GAME_LOCKS: return
            async with GAME_LOCKS[chat_id]:
                g = ACTIVE_GAMES.get(chat_id)
                if not g or g["status"] != "playing" or g.get("is_rolling") or g.get("view") == "rules": return
                if g["turn_index"] >= len(g["players"]): return
                if g["players"][g["turn_index"]]["id"] == -1:
                    await _execute_roll(context, chat_id, g, -1)
        except asyncio.CancelledError: pass
        except Exception as e: logger.error(f"Bot error: {e}")
        
    game["bot_task"] = asyncio.create_task(_bot_turn())

async def _execute_roll(context: ContextTypes.DEFAULT_TYPE, chat_id: int, game: dict, user_id: int):
    if not game or game["status"] != "playing" or game.get("is_rolling") or game.get("view") == "rules": return
    if game["turn_index"] >= len(game["players"]): return
    
    current = game["players"][game["turn_index"]]
    if current["id"] != user_id: return
    
    game["is_rolling"] = True
    msg_id = game["message_id"]
    
    if game.get("timer_task"): game["timer_task"].cancel()
    if game.get("bot_task"): game["bot_task"].cancel()
    
    try:
        # قفل کردن صفحه
        await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game, True))

        dice = random.randint(1, 6)
        game["last_dice"] = dice
        old_pos = current["pos"]
        
        if old_pos == 0 and dice != 6:
            game["last_action"] = f"🔒 {current['name']} برای ورود باید ۶ بیاورد! (تاس: {p_num(dice)})"
        else:
            target_pos = old_pos + dice if old_pos != 0 else dice
            if target_pos > MAX_POS:
                target_pos = MAX_POS - (target_pos - MAX_POS)
                game["last_action"] = f"🔄 {current['name']} تاس {p_num(dice)} آورد، از ۱۰۰ رد شد و برگشت به {p_num(target_pos)}."
            else:
                game["last_action"] = f"➡️ {current['name']} تاس {p_num(dice)} آورد و به خانه {p_num(target_pos)} رفت."
            
            current["pos"] = target_pos

            for p in game["players"]:
                if p["id"] != current["id"] and p["pos"] == target_pos:
                    p["pos"] = 0
                    game["last_action"] += f"\n💥 {p['name']} پرت شد به خانه ۱!"

            if target_pos in LADDERS:
                current["pos"] = LADDERS[target_pos]
                game["last_action"] += f"\n🪜 پله رفت به {p_num(current['pos'])}."
            elif target_pos in SNAKES:
                current["pos"] = SNAKES[target_pos]
                game["last_action"] += f"\n🐍 مار خورد به {p_num(current['pos'])}."
            elif target_pos in DRAGONS:
                current["pos"] = DRAGONS[target_pos]
                game["last_action"] += f"\n🐉 اژدها خورد به {p_num(current['pos'])}."
            elif target_pos in LUCK:
                current["pos"] = min(MAX_POS, target_pos + LUCK[target_pos])
                game["last_action"] += f"\n🎁 شانس آورد! {p_num(LUCK[target_pos])} خانه جلو رفت."
            elif target_pos in MISFORTUNE:
                current["pos"] = max(0, target_pos + MISFORTUNE[target_pos])
                game["last_action"] += f"\n⚡️ صاعقه خورد! {p_num(abs(MISFORTUNE[target_pos]))} خانه عقب افتاد."

        if current["pos"] == MAX_POS:
            game["status"] = "finished"
            game["last_action"] = f"🏆🎉 <b>تبریک به {current['name']}!</b>\n👑 با رسیدن به ۱۰۰ قهرمان شد!"
            await _safe_edit(context, chat_id, msg_id, _get_ui(game), None)
            _cleanup(chat_id)
            return

        if dice != 6: 
            game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
        else: 
            game["last_action"] += "\n(چون ۶ آورد، دوباره می‌ندازه!)"

    except Exception as e:
        logger.error(f"Roll error: {e}", exc_info=True)
        game["last_action"] = "⚠️ خطایی رخ داد، نوبت رد شد."
    finally:
        game["is_rolling"] = False
        if chat_id in ACTIVE_GAMES and game["status"] == "playing":
            # آپدیت صفحه با نتیجه نهایی
            await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game, False))
            
            next_p = game["players"][game["turn_index"]]
            if next_p["id"] == -1:
                _schedule_bot(context, chat_id, game)
            else:
                _schedule_timer(context, chat_id, game, next_p["id"])

async def cmd_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in ACTIVE_GAMES: 
        return await update.message.reply_text("⚠️ یک بازی در جریان است! اگر بازی گیر کرده، دکمه «🛑 بستن اجباری» را بزنید.")
    
    name = _get_safe_name(update.effective_user)
    ACTIVE_GAMES[chat_id] = {
        "status": "lobby", "view": "game", "host_id": update.effective_user.id, 
        "players": [{"id": update.effective_user.id, "name": name, "pos": 0, "icon": PLAYER_ICONS[0]}],
        "turn_index": 0, "last_action": "بازی ساخته شد.", "is_rolling": False, "last_dice": None, "message_id": None,
        "last_bump": 0, "timer_task": None, "bot_task": None
    }
    GAME_LOCKS[chat_id] = asyncio.Lock()
    
    msg = await update.message.reply_text(
        _get_ui(ACTIVE_GAMES[chat_id]), 
        parse_mode="HTML", 
        reply_markup=_get_lobby_kb(ACTIVE_GAMES[chat_id])
    )
    ACTIVE_GAMES[chat_id]["message_id"] = msg.message_id

async def handle_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    
    try: await query.answer()
    except Exception: pass
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    if chat_id not in ACTIVE_GAMES: 
        return await query.answer("بازی تمام شده است. /snake را بزنید.", show_alert=True)
    
    if chat_id not in GAME_LOCKS:
        GAME_LOCKS[chat_id] = asyncio.Lock()

    async with GAME_LOCKS[chat_id]:
        game = ACTIVE_GAMES.get(chat_id)
        if not game: return
        msg_id = game["message_id"]

        if query.data == "snake_wait":
            return await query.answer("لطفاً صبر کنید...", show_alert=False)

        # --- دکمه‌های مربوط به صفحه قوانین ---
        if query.data == "snake_rules":
            game["view"] = "rules"
            await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game))
            return

        if query.data == "snake_back":
            game["view"] = "game"
            kb = _get_lobby_kb(game) if game["status"] == "lobby" else _get_game_kb(game, game.get("is_rolling"))
            await _safe_edit(context, chat_id, msg_id, _get_ui(game), kb)
            return

        # --- دکمه بستن اجباری (نجات بازی) ---
        if query.data == "snake_force_stop":
            if game["status"] == "playing" and user.id != game["host_id"]:
                return await query.answer("فقط سازنده بازی می‌تواند بازی را ببندد!", show_alert=True)
            
            _cleanup(chat_id)
            await _safe_edit(context, chat_id, msg_id, "🛑 بازی توسط سازنده به طور کامل بسته شد.", None)
            return await query.answer("بازی بسته شد.", show_alert=True)

        # --- آوردن به پایین ---
        if query.data == "snake_bump":
            if not any(p["id"] == user.id for p in game["players"]): 
                return await query.answer("فقط بازیکنان!", show_alert=True)
            
            now = time.time()
            if now - game.get("last_bump", 0) < BUMP_COOLDOWN:
                return await query.answer(f"{BUMP_COOLDOWN} ثانیه صبر کنید.", show_alert=True)
            game["last_bump"] = now

            try: await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception: pass
            
            kb = _get_lobby_kb(game) if game["status"] == "lobby" else _get_game_kb(game, game.get("is_rolling"))
            new_msg = await context.bot.send_message(chat_id=chat_id, text=_get_ui(game), parse_mode="HTML", reply_markup=kb)
            game["message_id"] = new_msg.message_id
            return await query.answer("بازی پایین آمد! ⬇️", show_alert=False)

        # --- پیوستن ---
        if query.data == "snake_join":
            if game.get("is_rolling"): return await query.answer("در حال حرکت!", show_alert=True)
            if game["status"] != "lobby": return await query.answer("بازی شروع شده!", show_alert=True)
            if any(p["id"] == user.id for p in game["players"]): return await query.answer("قبلاً وارد شدید.", show_alert=True)
            if len(game["players"]) >= 4: return await query.answer("ظرفیت پر است.", show_alert=True)
            
            name = _get_safe_name(user)
            game["players"].append({"id": user.id, "name": name, "pos": 0, "icon": PLAYER_ICONS[len(game["players"])]})
            await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_lobby_kb(game))
            return

        # --- بازی با ربات ---
        if query.data == "snake_play_bot":
            if game["status"] != "lobby": return await query.answer("شروع شده!", show_alert=True)
            if any(p["id"] == -1 for p in game["players"]): return await query.answer("ربات هست.", show_alert=True)
            
            game["players"].append({"id": -1, "name": "🤖 ربات", "pos": 0, "icon": "🤖"})
            game["status"] = "playing"
            game["turn_index"] = 0
            game["last_action"] = "بازی شروع شد! (منتظر ۶ باشید)"
            
            await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game))
            _schedule_timer(context, chat_id, game, game["players"][0]["id"])
            return

        # --- شروع بازی ---
        if query.data == "snake_start":
            if game.get("is_rolling"): return await query.answer("در حال حرکت!", show_alert=True)
            if user.id != game["host_id"] or len(game["players"]) < 2: 
                return await query.answer("حداقل ۲ نفر و فقط سازنده!", show_alert=True)
                
            game["status"] = "playing"
            game["turn_index"] = 0
            game["last_action"] = "بازی شروع شد! (منتظر ۶ باشید)"
            
            await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game))
            _schedule_timer(context, chat_id, game, game["players"][0]["id"])
            return

        # --- انصراف ---
        if query.data == "snake_surrender":
            if game.get("is_rolling"): return await query.answer("در حال حرکت!", show_alert=True)
            p_idx = next((i for i, p in enumerate(game["players"]) if p["id"] == user.id), None)
            
            if p_idx is not None:
                s_p = game["players"].pop(p_idx)
                
                if len(game["players"]) < 2: 
                    _cleanup(chat_id)
                    await _safe_edit(context, chat_id, msg_id, f"🏳️ {s_p['name']} انصراف داد. بازی لغو شد.", None)
                    return
                
                if p_idx < game["turn_index"]:
                    game["turn_index"] -= 1
                elif p_idx == game["turn_index"]:
                    if game["turn_index"] >= len(game["players"]):
                        game["turn_index"] = 0
                
                curr = game["players"][game["turn_index"]]
                if curr["id"] == -1: _schedule_bot(context, chat_id, game)
                else: _schedule_timer(context, chat_id, game, curr["id"])

                await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game))
            return

        # --- پرتاب تاس ---
        if query.data == "snake_roll":
            if game.get("is_rolling"): return await query.answer("صبر کنید...", show_alert=True)
            if game["status"] != "playing": return await query.answer("شروع نشده!", show_alert=True)
            if user.id != game["players"][game["turn_index"]]["id"]: 
                return await query.answer("نوبت شما نیست!", show_alert=True)
                
            await _execute_roll(context, chat_id, game, user.id)
            return
