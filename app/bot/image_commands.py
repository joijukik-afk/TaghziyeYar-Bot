"""تولید عکس با هوش مصنوعی (Pollinations AI - رایگان و بدون کلید)."""

import io
import logging
import urllib.parse
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)


async def cmd_imagine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    if not context.args:
        return await update.message.reply_text(
            "🎨 <b>تولید عکس با هوش مصنوعی</b>\n\n"
            "توصیف عکسی که می‌خوای رو بنویس:\n"
            "<code>/imagine یک گربه فضانورد در مریخ</code>\n"
            "<code>/imagine دختر در باران، سبک سینمایی</code>\n"
            "<code>/imagine cyberpunk city at night</code>",
            parse_mode="HTML"
        )

    prompt_fa = " ".join(context.args).strip()[:500]
    status_msg = await update.message.reply_text("🎨 در حال خلق تصویر... (۵ تا ۱۵ ثانیه)")

    try:
        ai = get_ai_service()
        
        # ۱. ترجمه پرامپت به انگلیسی (هوش مصنوعی بهترین درک رو از انگلیسی داره)
        try:
            prompt_en = await ai.translate(prompt_fa, "en", user_id=update.effective_user.id)
            if not prompt_en or len(prompt_en) < 3:
                prompt_en = prompt_fa
        except Exception:
            prompt_en = prompt_fa

        # ۲. ساخت URL تصویر
        encoded = urllib.parse.quote(prompt_en)
        image_url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=1024&height=1024&nologo=true&model=flux&enhance=true"
        )

        # ۳. دانلود تصویر
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            
            if not resp.content or len(resp.content) < 1000:
                return await status_msg.edit_text("❌ خطا در تولید تصویر. لطفاً دوباره تلاش کنید.")
            
            img_io = io.BytesIO(resp.content)
            img_io.name = "imagine.jpg"

        # ۴. ارسال به کاربر
        caption = (
            f"🎨 <b>تصویر ساخته شد!</b>\n\n"
            f"📝 <b>پرامپت:</b> {prompt_fa}\n"
            f"🔤 <b>به انگلیسی:</b> <i>{prompt_en[:200]}</i>\n\n"
            f"🌟 ساخته شده با هوش مصنوعی"
        )
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 تصویر جدید", callback_data=f"reimagine_{prompt_fa[:50]}"),
            InlineKeyboardButton("🎨 همه عکس‌ها", url="https://t.me/" + (context.bot.username or ""))
        ]])
        
        await update.message.reply_photo(
            photo=img_io, caption=caption,
            parse_mode="HTML", reply_markup=keyboard
        )
        await status_msg.delete()

    except httpx.TimeoutException:
        await status_msg.edit_text("⏱️ ساخت تصویر خیلی طول کشید. لطفاً دوباره تلاش کنید یا پرامپت ساده‌تری بنویسید.")
    except Exception as e:
        logger.error(f"Imagine error: {e}", exc_info=True)
        await status_msg.edit_text("❌ متأسفانه در تولید تصویر خطایی رخ داد. چند لحظه بعد دوباره تلاش کنید.")
