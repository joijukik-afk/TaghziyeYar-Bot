"""Vision AI commands: Analyze images, OCR, Roast, Food."""

import base64
import logging
from telegram import Update
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

async def _process_image(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str, status_text: str):
    if not update.message or not update.effective_user:
        return
        
    photo = None
    if update.message.photo:
        photo = update.message.photo[-1] 
    elif update.message.reply_to_message and update.message.reply_to_message.photo:
        photo = update.message.reply_to_message.photo[-1]
        
    if not photo:
        return await update.message.reply_text("⚠️ لطفاً یک عکس بفرستید یا روی یک عکس ریپلای کنید.")

    status_msg = await update.message.reply_text(status_text)
    
    try:
        file = await context.bot.get_file(photo.file_id)
        img_bytes = await file.download_as_bytearray()
        img_base64 = base64.b64encode(bytes(img_bytes)).decode('utf-8')
        
        ai_service = get_ai_service()
        result = await ai_service.analyze_image(
            image_base64=img_base64, 
            prompt=prompt, 
            user_id=update.effective_user.id
        )
        
        try:
            await status_msg.edit_text(result, parse_mode="Markdown")
        except Exception:
            await status_msg.edit_text(result)
            
    except Exception as e:
        logger.error(f"Vision processing error: {e}")
        await status_msg.edit_text("❌ متأسفانه در پردازش عکس خطایی پیش آمد.")

async def cmd_vision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = "این عکس را با جزئیات کامل تحلیل کن. چه چیزهایی در آن وجود دارد؟ آن را به زبان فارسی روان بنویس."
    await _process_image(update, context, prompt, "👁️ در حال دیدن و تحلیل عکس...")

async def cmd_roast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = "این عکس را ببین. یک متن طنز، کنایه‌آمیز و خنده‌دار (اما دوستانه و بدون توهین) به زبان فارسی درباره‌ی چیزی که در عکس است بنویس. اصطلاحات اینستاگرامی و بامزه استفاده کن."
    await _process_image(update, context, prompt, "🔥 در حال آماده کردن متن طنز...")

async def cmd_ocr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = (
        "تمام متن‌های موجود در این عکس را دقیقاً استخراج کن. "
        "اگر متن انگلیسی یا به زبان دیگری بود، ابتدا متن اصلی را بنویس و سپس آن را به فارسی روان ترجمه کن."
    )
    await _process_image(update, context, prompt, "📝 در حال استخراج متن از عکس...")

async def cmd_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    prompt = (
        "این عکس مربوط به یک غذا است. لطفاً تشخیص بده چه غذایی است و موارد زیر را تخمین بزن:\n"
        "۱. نام غذا\n"
        "۲. کالری تقریبی\n"
        "۳. پروتئین، کربوهیدرات و چربی\n"
        "پاسخ را به فارسی و با فرمت زیبا بنویس."
    )
    await _process_image(update, context, prompt, "🍽️ در حال تحلیل ارزش غذایی غذا...")

async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user: return
    if update.effective_chat.type == "private":
        await cmd_vision(update, context)
