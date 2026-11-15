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

FONT_PATH = "Vazirmatn-Bold.ttf"
FONT_URL = "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Bold.ttf"

async def _ensure_font_exists():
    """دانلود خودکار فونت در صورت نبودن"""
    if not os.path.exists(FONT_PATH):
        logger.info("Font not found. Downloading Vazirmatn-Bold.ttf...")
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(FONT_URL)
                if response.status_code == 200:
                    with open(FONT_PATH, "wb") as f:
                        f.write(response.content)
                    logger.info("✅ Font downloaded successfully.")
        except Exception as e:
            logger.error(f"Failed to download font: {e}")

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
        # ۱. چک کردن و دانلود فونت
        await _ensure_font_exists()

        # ۲. آماده‌سازی متن (اصلاح حروف و راست‌چین)
        reshaped_text = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped_text)

        # ۳. ساخت بوم
        size = (512, 512)
        img = _create_gradient_background(size[0], size[1], (28, 30, 60), (70, 30, 90))
        draw = ImageDraw.Draw(img)

        # ۴. بارگذاری فونت
        try:
            font = ImageFont.truetype(FONT_PATH, 50)
        except IOError:
            font = ImageFont.load_default()

        # ۵. شکستن متن به خطوط
        wrapped_lines = textwrap.wrap(bidi_text, width=20)
        
        # محاسبه ارتفاع برای وسط‌چین شدن عمودی
        line_heights = [draw.textbbox((0, 0), line, font=font)[3] for line in wrapped_lines]
        total_text_height = sum(line_heights) + (len(wrapped_lines) - 1) * 15
        
        y_start = (512 - total_text_height) / 2

        # ۶. نوشتن متن
        for i, line in enumerate(wrapped_lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (512 - text_width) / 2
            
            # سایه
            draw.text((x + 2, y_start + 2), line, font=font, fill=(0, 0, 0, 180))
            # متن اصلی
            draw.text((x, y_start), line, font=font, fill=(255, 255, 255, 255))
            
            y_start += line_heights[i] + 15

        # ۷. ذخیره به عنوان WebP
        output = io.BytesIO()
        img.save(output, format="WebP", lossless=True)
        output.seek(0)

        # ۸. ارسال استیکر
        await update.message.reply_sticker(sticker=output)
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Sticker generation error: {e}", exc_info=True)
        await status_msg.edit_text("❌ متأسفانه در ساخت استیکر خطایی پیش آمد.")
