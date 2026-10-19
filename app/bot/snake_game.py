"""بازی فوق‌حرفه‌ای مار و پله با نقشه تصویری و انیمیشن زنده"""

import random
import logging
import io
import asyncio
from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# نقشه مارها و پله‌ها
LADDERS = {2: 38, 7: 14, 8: 31, 15: 26, 21: 42, 28: 84, 36: 44, 51: 67, 71: 91, 78: 98}
SNAKES = {16: 6, 46: 25, 49: 11, 62: 19, 64: 60, 74: 53, 89: 68, 92: 88, 95: 75, 99: 80}

ACTIVE_GAMES = {}
PLAYER_COLORS = [(255, 0, 0), (0, 0, 255), (0, 200, 0), (255, 215, 0)] # قرمز، آبی، سبز، زرد

# ابعاد مپ
CELL_SIZE = 80
BOARD_SIZE = 800

def _pos_to_xy(pos: int):
    """تبدیل شماره خانه به مختصات X و Y روی تصویر"""
    if pos == 0: return (BOARD_SIZE // 2, BOARD_SIZE - 20) # استارت
    row = (pos - 1) // 10
    col = (pos - 1) % 10
    
    # اگر ردیف زوج است، از راست به چپ (مارپیچ)
    if row % 2 != 0:
        col = 9 - col
        
    # محاسبه X و Y (از پایین به بالا)
    x = col * CELL_SIZE + CELL_SIZE // 2
    y = BOARD_SIZE - (row * CELL_SIZE) - CELL_SIZE // 2
    return (x, y)

def _draw_board(players: list) -> io.BytesIO:
    """ساخت تصویر مپ بازی"""
    img = Image.new("RGB", (BOARD_SIZE, BOARD_SIZE), "white")
    draw = ImageDraw.Draw(img)
    
    # ۱. کشیدن خانه‌های ۱۰۰گانه
    for pos in range(1, 101):
        row = (pos - 1) // 10
        col = (pos - 1) % 10
        if row % 2 != 0: col = 9 - col
        
        x1 = col * CELL_SIZE
        y1 = BOARD_SIZE - (row + 1) * CELL_SIZE
        x2 = x1 + CELL_SIZE
        y2 = y1 + CELL_SIZE
        
        # رنگ‌بندی شطرنجی
        color = (240, 248, 255) if (row + col) % 2 == 0 else (200, 220, 240)
        draw.rectangle([x1, y1, x2, y2], fill=color, outline="black", width=2)
        
        # نوشتن شماره خانه
        try:
            font = ImageFont.truetype("Vazirmatn-Bold.ttf", 15)
        except:
            font = ImageFont.load_default()
            
        draw.text((x1 + 5, y1 + 5), str(pos), fill="black", font=font)

    # ۲. کشیدن پله‌ها (خطوط سبز)
    for start, end in LADDERS.items():
        start_xy = _pos_to_xy(start)
        end_xy = _pos_to_xy(end)
        draw.line([start_xy, end_xy], fill="green", width=5)
        
    # ۳. کشیدن مارها (خطوط قرمز)
    for start, end in SNAKES.items():
        start_xy = _pos_to_xy(start)
        end_xy = _pos_to_xy(end)
        draw.line([start_xy, end_xy], fill="red", width=5)

    # ۴. کشیدن مهره بازیکنان
    for idx, p in enumerate(players):
        if p["pos"] >= 0:
            x, y = _pos_to_xy(p["pos"])
            # کمی جابجایی برای اینکه اگر دو نفر روی یک خانه بودن، روی هم نیفتن
            offset = (idx % 2) * 15 - 7
            
            color = PLAYER_COLORS[idx]
            draw.ellipse([x-15+offset, y-15+offset, x+15+offset, y+15+offset], fill=color, outline="black", width=2)
            
            # نوشتن اسم کوچک روی مهره
            try:
                font = ImageFont.truetype("Vazirmatn-Bold.ttf", 12)
            except:
                font = ImageFont.load_default()
            draw.text((x-5+offset, y-6+offset), str(idx+1), fill="white", font=font)

    img_io = io.BytesIO()
    img.save(img_io, format="JPEG", quality=85)
    img_io.seek(0)
    img_io.name = "board.jpg"
    return img_io

def _get_game_text(game: dict) -> str:
    """ساخت متن وضعیت"""
    if game["status"] == "lobby":
        text = "🐍 <b>مار و پله تصویری</b> 🪜\n\n"
        text += "⏳ در انتظار بازیکنان...\n"
        for idx, p in enumerate(game["players"]):
            text += f"👤 {p['name']} (بازیکن {idx+1})\n"
        return text
    else:
        current = game["players"][game["turn_index"]]
        text = f"🎲 <b>نوبت:</b> {current['name']} (بازیکن {game['turn_index']+1})\n"
        if game.get("last_action"):
            text += f"📢 <i>{game['last_action']}</i>\n\n"
        
        for idx, p in enumerate(game["players"]):
            text += f"مهره {idx+1} ({p['name']}): خانه {p['pos']}\n"
        return text

def _lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 ورود به بازی", callback_data="snake_join")],
        [InlineKeyboardButton("🚀 شروع بازی (میزبان)", callback_data="snake_start")]
    ])

def _dice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎲 پرتاب تاس", callback_data="snake_roll")]])

async def cmd_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in ACTIVE_GAMES:
        await update.message.reply_text("⚠️ یک بازی در جریان است!")
        return

    ACTIVE_GAMES[chat_id] = {
        "status": "lobby",
        "host_id": update.effective_user.id,
        "players": [{"id": update.effective_user.id, "name": update.effective_user.first_name, "pos": 0}],
        "turn_index": 0,
        "last_action": "بازی ساخته شد.",
        "message_id": None
    }

    board_img = _draw_board(ACTIVE_GAMES[chat_id]["players"])
    msg = await update.message.reply_photo(
        photo=board_img,
        caption=_get_game_text(ACTIVE_GAMES[chat_id]),
        parse_mode="HTML",
        reply_markup=_lobby_keyboard()
    )
    ACTIVE_GAMES[chat_id]["message_id"] = msg.message_id

async def handle_snake(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = update.effective_chat.id
    user = update.effective_user

    if chat_id not in ACTIVE_GAMES:
        await query.answer("بازی تمام شده است.", show_alert=True); return

    game = ACTIVE_GAMES[chat_id]

    # ورود
    if query.data == "snake_join":
        if game["status"] != "lobby" or any(p["id"] == user.id for p in game["players"]) or len(game["players"]) >= 4:
            await query.answer("امکان ورود نیست (بازی شروع شده یا پر است یا قبلا وارد شدید).", show_alert=True); return
        
        game["players"].append({"id": user.id, "name": user.first_name, "pos": 0})
        await query.answer("✅ وارد شدید!")
        board_img = _draw_board(game["players"])
        await query.edit_message_media(media=InputMediaPhoto(board_img, caption=_get_game_text(game), parse_mode="HTML"), reply_markup=_lobby_keyboard())
        return

    # شروع
    if query.data == "snake_start":
        if user.id != game["host_id"] or len(game["players"]) < 2:
            await query.answer("فقط میزبان با حداقل ۲ نفر می‌تواند شروع کند.", show_alert=True); return
        
        game["status"] = "playing"
        game["turn_index"] = 0
        game["last_action"] = "بازی شروع شد! تاس بیندازید."
        board_img = _draw_board(game["players"])
        await query.edit_message_media(media=InputMediaPhoto(board_img, caption=_get_game_text(game), parse_mode="HTML"), reply_markup=_dice_keyboard())
        return

    # پرتاب تاس و انیمیشن حرکت
    if query.data == "snake_roll":
        if game["status"] != "playing" or user.id != game["players"][game["turn_index"]]["id"]:
            await query.answer("نوبت شما نیست!", show_alert=True); return

        await query.answer("در حال حرکت...")
        current_player = game["players"][game["turn_index"]]
        
        dice = random.randint(1, 6)
        old_pos = current_player["pos"]
        target_pos = old_pos + dice
        
        # اگر از ۱۰۰ رد شد
        if target_pos > 100:
            target_pos = old_pos
            game["last_action"] = f"{current_player['name']} تاس {dice} آورد اما از ۱۰۰ رد شد."
        else:
            game["last_action"] = f"{current_player['name']} تاس {dice} آورد."
            
            # 🏃‍♂️ انیمیشن حرکت قدم به قدم
            for step in range(old_pos + 1, target_pos + 1):
                current_player["pos"] = step
                board_img = _draw_board(game["players"])
                await query.edit_message_media(
                    media=InputMediaPhoto(board_img, caption=_get_game_text(game), parse_mode="HTML"),
                    reply_markup=_dice_keyboard()
                )
                await asyncio.sleep(0.4) # تاخیر برای دیدن حرکت

            # 🐍 و 🪜 بررسی مار و پله
            if current_player["pos"] in LADDERS:
                game["last_action"] = f"🪜 {current_player['name']} پله رفت! از {current_player['pos']} به {LADDERS[current_player['pos']]}"
                current_player["pos"] = LADDERS[current_player["pos"]]
                await asyncio.sleep(0.5)
                board_img = _draw_board(game["players"])
                await query.edit_message_media(media=InputMediaPhoto(board_img, caption=_get_game_text(game), parse_mode="HTML"), reply_markup=_dice_keyboard())
                
            elif current_player["pos"] in SNAKES:
                game["last_action"] = f"🐍 {current_player['name']} مار خورد! از {current_player['pos']} به {SNAKES[current_player['pos']]}"
                current_player["pos"] = SNAKES[current_player["pos"]]
                await asyncio.sleep(0.5)
                board_img = _draw_board(game["players"])
                await query.edit_message_media(media=InputMediaPhoto(board_img, caption=_get_game_text(game), parse_mode="HTML"), reply_markup=_dice_keyboard())

        # بررسی برد
        if current_player["pos"] == 100:
            game["status"] = "finished"
            game["last_action"] = f"🏆 <b>{current_player['name']} برنده شد!</b> 🎉"
            board_img = _draw_board(game["players"])
            await query.edit_message_media(media=InputMediaPhoto(board_img, caption=_get_game_text(game), parse_mode="HTML"), reply_markup=None)
            del ACTIVE_GAMES[chat_id]
            return

        # تغییر نوبت (اگر ۶ نیاورده باشد)
        if dice != 6:
            game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
        else:
            game["last_action"] += " (چون ۶ آورد، دوباره تاس می‌ریزد!)"

        board_img = _draw_board(game["players"])
        await query.edit_message_media(
            media=InputMediaPhoto(board_img, caption=_get_game_text(game), parse_mode="HTML"),
            reply_markup=_dice_keyboard()
        )
        return
