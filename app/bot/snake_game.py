"""بازی مار و پله - نسخه نهایی (رفع کامل فریز شدن ربات و اصلاح متن‌ها)"""

import random
import logging
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

logger = logging.getLogger(__name__)

# تنظیمات بازی
LADDERS = {1: 38, 4: 14, 9: 31, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 80: 100}
SNAKES = {16: 6, 47: 26, 49: 11, 56: 53, 62: 19, 64: 60, 87: 24, 93: 73, 95: 75, 98: 78}
DRAGONS = {20: 5, 40: 15, 70: 35, 90: 55}
LUCK = {10: 5, 35: 10, 60: 15, 85: 10}
MISFORTUNE = {30: -5, 50: -10, 75: -5, 97: -10}

MAX_POS = 100
TURN_TIMEOUT = 40  # ثانیه
PLAYER_ICONS = ["🦊", "🐼", "🦁", "🐸"]
BOT_ICON = "🤖"

ACTIVE_GAMES = {}

def p_num(n: int) -> str:
    return str(n).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))

def fix_dir(text: str) -> str:
    """اصلاح جهت متن برای جلوگیری از برعکس شدن اعداد و پرانتزها"""
    return f"\u2066{text}\u2069"

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
        if p["pos"] > 0: cells[p["pos"]] = p["icon"]

    lines = []
    for row in range(10, 0, -1):
        line = ""
        cols = range(1, 11) if row % 2 != 0 else range(10, 0, -1)
        for col in cols:
            pos = (row - 1) * 10 + col
            val = cells.get(pos)
            if val: line += f"{val:^4}"
            else: line += f"{pos:^4}" if pos < 100 else " 100"
        lines.append(line)
    return f"<pre dir=\"ltr\">{chr(10).join(lines)}</pre>"

def _get_ui(game: dict) -> str:
    if game["status"] == "lobby":
        text = "🐍 <b>لابی بازی مار و پله</b> 🪜\n\n"
        text += f"👥 بازیکنان ({p_num(len(game['players']))}/۴):\n"
        for p in game["players"]: text += f"👤 {p['icon']} {p['name']}\n"
        text += "\n👇 برای ورود کلیک کنید."
        return text
    
    current = game["players"][game["turn_index"]]
    if current["id"] == -1: 
        header = f"{BOT_ICON} <b>نوبت حریف هوش مصنوعی است...</b>"
    else:
        mention = f"<a href='tg://user?id={current['id']}'>{current['name']}</a>"
        dice_str = f" | 🎲 {fix_dir(p_num(game['last_dice']))}" if game.get('last_dice') else ""
        header = f"🔔 <b>نوبت:</b> {current['icon']} {mention}{dice_str}"

    map_text = f"\n🗺 <b>نقشه:</b>\n{_draw_board(game['players'])}\n"

    stats = "\n📊 <b>آمار:</b>\n"
    for idx, p in enumerate(game["players"]):
        circle = "🟢" if idx == game["turn_index"] else "⚪"
        pos_text = "⏳ منتظر ۶" if p["pos"] == 0 else ("🏆 برنده" if p["pos"] == MAX_POS else f"خانه {fix_dir(p_num(p['pos']))}")
        stats += f"{circle} {p['icon']} {p['name']}: {pos_text}\n"
        
    events = f"\n📢 <i>{game.get('last_action', '')}</i>"
    return f"{header}{map_text}{stats}{events}"

def _get_lobby_kb(game: dict) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(f"🎮 ورود ({fix_dir(p_num(len(game['players'])))}/۴)", callback_data="snake_join")],
        [InlineKeyboardButton("🤖 بازی با ربات", callback_data="snake_play_bot")],
        [InlineKeyboardButton("📜 قوانین بازی", callback_data="snake_rules")]
    ]
    if len(game["players"]) >= 2: 
        kb.insert(1, [InlineKeyboardButton("🚀 شروع بازی", callback_data="snake_start")])
    kb.append([InlineKeyboardButton("🛑 بستن لابی", callback_data="snake_stop")])
    return InlineKeyboardMarkup(kb)

def _get_game_kb(game: dict, is_rolling: bool = False) -> InlineKeyboardMarkup:
    if is_rolling:
        return InlineKeyboardMarkup([[InlineKeyboardButton("⏳ در حال حرکت...", callback_data="snake_wait")]])
    
    kb = []
    if game["status"] == "playing":
        kb.append([InlineKeyboardButton("🎲 پرتاب تاس", callback_data="snake_roll")])
        kb.append([InlineKeyboardButton("⬇️ آوردن به پایین", callback_data="snake_bump")])
        kb.append([InlineKeyboardButton("📜 قوانین بازی", callback_data="snake_rules")])
        kb.append([InlineKeyboardButton("❌ انصراف", callback_data="snake_surrender")])
        kb.append([InlineKeyboardButton("🛑 بستن اجباری", callback_data="snake_stop")])
    return InlineKeyboardMarkup(kb) if kb else None

async def _safe_edit(context: ContextTypes.DEFAULT_TYPE, chat_id: int, msg_id: int, text: str, kb=None):
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=text,
            parse_mode="HTML", reply_markup=kb
        )
    except BadRequest as e:
        err = str(e).lower()
        if "message is not modified" not in err:
            if "message to edit not found" in err:
                if chat_id in ACTIVE_GAMES:
                    msg = await context.bot.send_message(chat_id, text=text, parse_mode="HTML", reply_markup=kb)
                    ACTIVE_GAMES[chat_id]["message_id"] = msg.message_id
            else:
                logger.warning(f"Edit failed: {e}")
    except Exception as e:
        logger.error(f"Edit error: {e}")

def _stop_game(chat_id: int):
    if chat_id in ACTIVE_GAMES:
        game = ACTIVE_GAMES[chat_id]
        if game.get("timer_job"): game["timer_job"].schedule_removal()
        if game.get("bot_job"): game["bot_job"].schedule_removal()
        del ACTIVE_GAMES[chat_id]

def _schedule_next(context: ContextTypes.DEFAULT_TYPE, chat_id: int, game: dict):
    # حذف جاب‌های قبلی
    if game.get("timer_job"): game["timer_job"].schedule_removal()
    if game.get("bot_job"): game["bot_job"].schedule_removal()

    next_p = game["players"][game["turn_index"]]
    
    async def _timer_callback(ctx: ContextTypes.DEFAULT_TYPE):
        if chat_id in ACTIVE_GAMES:
            g = ACTIVE_GAMES[chat_id]
            if g["status"] == "playing" and not g.get("is_rolling"):
                if g["players"][g["turn_index"]]["id"] == next_p["id"]:
                    if next_p["id"] != -1:
                        g["last_action"] = f"⏰ زمان {next_p['name']} تمام شد!"
                    await _do_roll(ctx, chat_id, g, next_p["id"])

    # استفاده از JobQueue استاندارد (بدون کرش و فریز شدن)
    if next_p["id"] == -1:
        game["bot_job"] = context.job_queue.run_once(_timer_callback, when=1.0, chat_id=chat_id)
    else:
        game["timer_job"] = context.job_queue.run_once(_timer_callback, when=TURN_TIMEOUT, chat_id=chat_id)

async def _do_roll(context: ContextTypes.DEFAULT_TYPE, chat_id: int, game: dict, user_id: int):
    if game.get("is_rolling"): return
    if game["turn_index"] >= len(game["players"]): return
    
    current = game["players"][game["turn_index"]]
    if current["id"] != user_id: return
    
    game["is_rolling"] = True
    msg_id = game["message_id"]
    
    if game.get("timer_job"): game["timer_job"].schedule_removal()
    if game.get("bot_job"): game["bot_job"].schedule_removal()

    try:
        await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game, True))

        dice = random.randint(1, 6)
        game["last_dice"] = dice
        old_pos = current["pos"]
        
        if old_pos == 0 and dice != 6:
            game["last_action"] = f"🔒 {current['name']} برای شروع باید ۶ بیاورد! (تاس: {fix_dir(p_num(dice))})"
        else:
            target = old_pos + dice if old_pos != 0 else dice
            if target > MAX_POS:
                target = MAX_POS - (target - MAX_POS)
                game["last_action"] = f"🔄 {current['name']} از ۱۰۰ رد شد و برگشت به {fix_dir(p_num(target))}."
            else:
                game["last_action"] = f"➡️ {current['name']} تاس {fix_dir(p_num(dice))} آورد و به {fix_dir(p_num(target))} رفت."
            
            current["pos"] = target
            for p in game["players"]:
                if p["id"] != current["id"] and p["pos"] == target:
                    p["pos"] = 0
                    game["last_action"] += f"\n💥 {p['name']} به خانه ۱ پرت شد!"

            if target in LADDERS:
                current["pos"] = LADDERS[target]
                game["last_action"] += f"\n🪜 پله رفت به {fix_dir(p_num(current['pos']))}."
            elif target in SNAKES:
                current["pos"] = SNAKES[target]
                game["last_action"] += f"\n🐍 مار خورد به {fix_dir(p_num(current['pos']))}."
            elif target in DRAGONS:
                current["pos"] = DRAGONS[target]
                game["last_action"] += f"\n🐉 اژدها خورد به {fix_dir(p_num(current['pos']))}."
            elif target in LUCK:
                current["pos"] = min(MAX_POS, target + LUCK[target])
                game["last_action"] += f"\n🎁 شانس آورد! {fix_dir(p_num(LUCK[target]))} خانه جلو رفت."
            elif target in MISFORTUNE:
                current["pos"] = max(0, target + MISFORTUNE[target])
                game["last_action"] += f"\n⚡️ صاعقه خورد! {fix_dir(p_num(abs(MISFORTUNE[target])))} خانه عقب افتاد."

        if current["pos"] == MAX_POS:
            game["status"] = "finished"
            game["last_action"] = f"🏆🎉 <b>تبریک به {current['name']}!</b>\n👑 با رسیدن به ۱۰۰ قهرمان شد!"
            await _safe_edit(context, chat_id, msg_id, _get_ui(game), None)
            _stop_game(chat_id)
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
            await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game, False))
            _schedule_next(context, chat_id, game)

async def cmd_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in ACTIVE_GAMES: 
        return await update.message.reply_text("⚠️ یک بازی در جریان است! اگر گیر کرده، دکمه «🛑 بستن اجباری» را بزنید.")
    
    name = _get_safe_name(update.effective_user)
    ACTIVE_GAMES[chat_id] = {
        "status": "lobby", "host_id": update.effective_user.id, 
        "players": [{"id": update.effective_user.id, "name": name, "pos": 0, "icon": PLAYER_ICONS[0]}],
        "turn_index": 0, "last_action": "بازی ساخته شد.", "is_rolling": False, "last_dice": None, "message_id": None,
        "timer_job": None, "bot_job": None
    }
    
    msg = await update.message.reply_text(
        _get_ui(ACTIVE_GAMES[chat_id]), 
        parse_mode="HTML", 
        reply_markup=_get_lobby_kb(ACTIVE_GAMES[chat_id])
    )
    ACTIVE_GAMES[chat_id]["message_id"] = msg.message_id

async def handle_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    
    if query.data == "snake_rules":
        rules = (
            "📜 قوانین مار و پله:\n"
            "🎲 شروع با ۶.\n"
            "🔄 با ۶ دوباره بنداز.\n"
            "💥 روی حریف بیفتی، به خانه ۱ میره.\n"
            "🪜 پله جلو، 🐍 مار و 🐉 اژدها عقب.\n"
            "🎁 شانس جلو، ⚡️ صاعقه عقب.\n"
            "🏆 اولین نفر به ۱۰۰ برنده است."
        )
        return await query.answer(rules, show_alert=True)

    try: await query.answer()
    except Exception: pass
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    if chat_id not in ACTIVE_GAMES: 
        return await query.answer("بازی تمام شده است. /snake را بزنید.", show_alert=True)
    
    game = ACTIVE_GAMES[chat_id]
    msg_id = game["message_id"]

    if query.data == "snake_wait":
        return await query.answer("لطفاً صبر کنید...", show_alert=False)

    if query.data == "snake_stop":
        if game["status"] == "playing" and user.id != game["host_id"]:
            return await query.answer("فقط سازنده می‌تواند ببندد!", show_alert=True)
        _stop_game(chat_id)
        await _safe_edit(context, chat_id, msg_id, "🛑 بازی بسته شد.", None)
        return await query.answer("بازی بسته شد.", show_alert=True)

    if query.data == "snake_bump":
        if not any(p["id"] == user.id for p in game["players"]): 
            return await query.answer("فقط بازیکنان!", show_alert=True)
        try: await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception: pass
        kb = _get_lobby_kb(game) if game["status"] == "lobby" else _get_game_kb(game, game.get("is_rolling"))
        new_msg = await context.bot.send_message(chat_id=chat_id, text=_get_ui(game), parse_mode="HTML", reply_markup=kb)
        game["message_id"] = new_msg.message_id
        return await query.answer("بازی پایین آمد! ⬇️", show_alert=False)

    if query.data == "snake_join":
        if game.get("is_rolling"): return await query.answer("در حال حرکت!", show_alert=True)
        if game["status"] != "lobby": return await query.answer("شروع شده!", show_alert=True)
        if any(p["id"] == user.id for p in game["players"]): return await query.answer("وارد شدید.", show_alert=True)
        if len(game["players"]) >= 4: return await query.answer("ظرفیت پر است.", show_alert=True)
        
        name = _get_safe_name(user)
        game["players"].append({"id": user.id, "name": name, "pos": 0, "icon": PLAYER_ICONS[len(game["players"])]})
        await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_lobby_kb(game))
        return

    if query.data == "snake_play_bot":
        if game["status"] != "lobby": return await query.answer("شروع شده!", show_alert=True)
        game["players"].append({"id": -1, "name": "حریف هوش مصنوعی", "pos": 0, "icon": BOT_ICON})
        game["status"] = "playing"
        game["turn_index"] = 0
        game["last_action"] = "بازی شروع شد! (منتظر ۶ باشید)"
        
        await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game))
        _schedule_next(context, chat_id, game)
        return

    if query.data == "snake_start":
        if user.id != game["host_id"] or len(game["players"]) < 2: 
            return await query.answer("حداقل ۲ نفر و فقط سازنده!", show_alert=True)
        game["status"] = "playing"
        game["turn_index"] = 0
        game["last_action"] = "بازی شروع شد! (منتظر ۶ باشید)"
        
        await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game))
        _schedule_next(context, chat_id, game)
        return

    if query.data == "snake_surrender":
        if game.get("is_rolling"): return await query.answer("در حال حرکت!", show_alert=True)
        p_idx = next((i for i, p in enumerate(game["players"]) if p["id"] == user.id), None)
        
        if p_idx is not None:
            s_p = game["players"].pop(p_idx)
            if len(game["players"]) < 2: 
                _stop_game(chat_id)
                await _safe_edit(context, chat_id, msg_id, f"🏳️ {s_p['name']} انصراف داد. بازی لغو شد.", None)
                return
            
            if p_idx < game["turn_index"]: game["turn_index"] -= 1
            elif p_idx == game["turn_index"] and game["turn_index"] >= len(game["players"]): game["turn_index"] = 0
            
            await _safe_edit(context, chat_id, msg_id, _get_ui(game), _get_game_kb(game))
            _schedule_next(context, chat_id, game)
        return

    if query.data == "snake_roll":
        if game.get("is_rolling"): return await query.answer("صبر کنید...", show_alert=True)
        if game["status"] != "playing": return await query.answer("شروع نشده!", show_alert=True)
        if user.id != game["players"][game["turn_index"]]["id"]: 
            return await query.answer("نوبت شما نیست!", show_alert=True)
            
        await _do_roll(context, chat_id, game, user.id)
        return
