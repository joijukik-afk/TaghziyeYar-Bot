"""Text to Sticker generator using Pillow with Auto-Font-Download."""

import io
import os
import logging
import textwrap
import httpx
import arabic_reshaper
from bidi.algorithm import get_display
from telegram import Update
from telegram.ext import ContextTypes
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# پیدا کردن مسیر دقیق فونت (از داخل پوشه app/bot به روت پروژه)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FONT_PATH = os.path.join(BASE_DIR, "Vazirmatn-Bold.ttf")

async def _ensure_font_exists() -> bool:
    """چک کردن وجود فونت در پروژه"""
    if os.path.exists(FONT_PATH):
        return True
    else:
        logger.error(f"Font NOT found at: {FONT_PATH}")
        return False

def _create_gradient_background(width: int, height: int, color1: tuple, color2: tuple) -> Image.Image:
    """ساخت پس‌زمینه گرادیانت زیبا"""
    base = Image.new('RGB', (width, height), color1)
    top = Image.new('RGB', (width, height), color2)
    mask = Image.new('L', (width, height))
    mask_data = []
    for y in range(height):
        for x in range(width):
            mask_data.append(int(255 * (y / height)))
    mask.putdata(mask_data)
    base.paste(top, (0, 0), mask)
    return base

async def cmd_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user: return

    text = " ".join(context.args) if context.args else ""
    if not text and update.message.reply_to_message:
        text = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""

    if not text.strip():
        return await update.message.reply_text(
            "🎨 **راهنمای استیکرساز**\n\n"
            "یک متن بنویس تا برات استیکر بسازم:\n"
            "`/sticker سلام دنیا`\n"
            "یا روی یک متن ریپلای کن و بنویس `/sticker`",
            parse_mode="Markdown"
        )

    status_msg = await update.message.reply_text("🎨 در حال طراحی استیکر...")

    try:
        # ۱. چک کردن فونت
        font_ok = await _ensure_font_exists()
        if not font_ok:
            return await status_msg.edit_text("❌ فایل فونت پیدا نشد!\nمطمئن شو فایل Vazirmatn-Bold.ttf کنار requirements.txt هست.")

        # ۲. ساخت بوم
        size = (512, 512)
        img = _create_gradient_background(size[0], size[1], (28, 30, 60), (70, 30, 90))
        draw = ImageDraw.Draw(img)

        # ۳. بارگذاری فونت
        try:
            font = ImageFont.truetype(FONT_PATH, 50)
        except IOError:
            return await status_msg.edit_text("❌ فونت خراب است یا خوانده نمی‌شود.")

        # ۴. شکستن متن به خطوط
        wrapped_lines = textwrap.wrap(text, width=20)
        
        line_heights = []
        bidi_lines = []
        
        for line in wrapped_lines:
            # چسباندن حروف فارسی و سپس اصلاح جهت (راست‌چین)
            reshaped = arabic_reshaper.reshape(line)
            bidi_line = get_display(reshaped)
            bidi_lines.append(bidi_line)
            
            bbox = draw.textbbox((0, 0), bidi_line, font=font)
            line_heights.append(bbox[3] - bbox[1])
            
        total_text_height = sum(line_heights) + (len(wrapped_lines) - 1) * 15
        y_start = (512 - total_text_height) / 2

        # ۵. نوشتن متن
        for i, bidi_line in enumerate(bidi_lines):
            bbox = draw.textbbox((0, 0), bidi_line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (512 - text_width) / 2
            
            # سایه
            draw.text((x + 2, y_start + 2), bidi_line, font=font, fill=(0, 0, 0, 180))
            # متن اصلی
            draw.text((x, y_start), bidi_line, font=font, fill=(255, 255, 255, 255))
            
            y_start += line_heights[i] + 15

        # ۶. ذخیره به عنوان WebP
        output = io.BytesIO()
        img.save(output, format="WebP", lossless=True)
        output.seek(0)

        # ۷. ارسال استیکر
        await update.message.reply_sticker(sticker=output)
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Sticker generation error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ متأسفانه خطایی پیش آمد:\n`{str(e)[:100]}`", parse_mode="Markdown")
