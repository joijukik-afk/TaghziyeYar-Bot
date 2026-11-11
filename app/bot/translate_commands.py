"""Translation commands handler."""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

async def cmd_translate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    text_to_translate = ""
    target_lang = "fa" # زبان پیش‌فرض مقصد (فارسی)

    # ۱. بررسی دستور کاربر
    if context.args:
        if len(context.args[0]) == 2 and context.args[0].isalpha():
            target_lang = context.args[0].lower()
            text_to_translate = " ".join(context.args[1:])
        else:
            text_to_translate = " ".join(context.args)

    # ۲. اگر روی یک پیام ریپلای کرده بود
    if not text_to_translate and update.message.reply_to_message:
        replied_msg = update.message.reply_to_message
        text_to_translate = replied_msg.text or replied_msg.caption or ""

    # ۳. اگر متنی پیدا نشد
    if not text_to_translate.strip():
        await update.message.reply_text(
            "⚠️ **راهنمای ترجمه:**\n\n"
            "۱️⃣ روی یک پیام ریپلای کنید و بنویسید: `/translate en` (برای ترجمه به انگلیسی)\n"
            "۲️⃣ یا متن را مستقیم بفرستید: `/translate en Hello world`\n\n"
            "🌐 زبان‌های پیشنهادی: `fa` (فارسی)، `en` (انگلیسی)، `ar` (عربی)، `tr` (ترکی)",
            parse_mode="Markdown"
        )
        return

    status_msg = await update.message.reply_text("⏳ در حال ترجمه...")

    try:
        ai_service = get_ai_service()
        translated_text = await ai_service.translate(
            text=text_to_translate, 
            target_language=target_lang,
            user_id=update.effective_user.id
        )
        
        lang_names = {"fa": "فارسی 🇮🇷", "en": "انگلیسی 🇬🇧", "ar": "عربی 🇸🇦", "tr": "ترکی 🇹🇷"}
        lang_display = lang_names.get(target_lang, target_lang)
        
        await status_msg.edit_text(f"🌐 **ترجمه به {lang_display}:**\n\n{translated_text}")
        
    except Exception as e:
        logger.error(f"Translation error: {e}")
        await status_msg.edit_text("❌ متأسفانه در ترجمه خطایی پیش آمد.")
