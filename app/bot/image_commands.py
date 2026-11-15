"""تولید عکس با هوش مصنوعی (Pollinations AI - رایگان و بدون کلید)."""

import io
import logging
import urllib.parse
import hashlib
import httpx
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service
from app.utils.message_formatter import with_signature

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
        
        try:
            prompt_en = await ai.translate(prompt_fa, "en", user_id=update.effective_user.id)
            if not prompt_en or len(prompt_en) < 3:
                prompt_en = prompt_fa
        except Exception as e:
            logger.warning(f"Translation for image prompt failed: {e}")
            prompt_en = prompt_fa

        encoded = urllib.parse.quote(prompt_en)
        image_url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            f"?width=1024&height=1024&nologo=true&model=flux&enhance=true"
        )

        async with httpx.AsyncClient(timeout=45.0, follow_redirects=True) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            
            try:
                img_io = io.BytesIO(resp.content)
                img = Image.open(img_io)
                img.verify() 
                img_io.seek(0)
                img_io.name = "imagine.jpg"
            except Exception as img_err:
                logger.error(f"Invalid image received: {img_err}")
                return await status_msg.edit_text("❌ سرور تصویر، فایل معتبری برنگرداند. دوباره تلاش کنید.")

        caption = (
            f"🎨 <b>تصویر ساخته شد!</b>\n\n"
            f"📝 <b>پرامپت:</b> {prompt_fa}\n"
            f"🔤 <b>به انگلیسی:</b> <i>{prompt_en[:200]}</i>\n\n"
            f"🌟 ساخته شده با هوش مصنوعی"
        )
        
        prompt_hash = hashlib.md5(prompt_fa.encode()).hexdigest()[:10]
        context.user_data[f"reimagine_{prompt_hash}"] = prompt_fa
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔄 تصویر جدید", callback_data=f"reimg_{prompt_hash}")
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


async def handle_reimagine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """هندلر دکمه تصویر جدید"""
    query = update.callback_query
    if not query: return
    await query.answer()
    
    data = query.data or ""
    if not data.startswith("reimg_"): return
    
    prompt_hash = data.replace("reimg_", "")
    prompt_fa = context.user_data.get(f"reimagine_{prompt_hash}")
    
    if not prompt_fa:
        return await query.edit_message_text("⚠️ پرامپت اصلی پیدا نشد. لطفاً دستور /imagine را دوباره بزنید.")
    
    context.args = prompt_fa.split()
    await query.message.reply_text("🔄 در حال ساخت تصویر جدید...")
    await cmd_imagine(update, context)
