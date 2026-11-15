"""Translation commands handler."""

import html
import logging
import re
import time
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from app.services.ai_service import get_ai_service
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

SUPPORTED_LANGS = {
    "fa": "فارسی 🇮🇷", "en": "انگلیسی 🇬🇧", "ar": "عربی 🇸🇦", "tr": "ترکی 🇹🇷",
    "de": "آلمانی 🇩🇪", "fr": "فرانسوی 🇫🇷", "es": "اسپانیایی 🇪🇸", "ru": "روسی 🇷🇺",
    "zh": "چینی 🇨🇳", "ja": "ژاپنی 🇯🇵",
}

_TRANSLATE_COOLDOWN = 3
_last_translate_time: dict[int, float] = {}

def _parse_lang_and_text(args: list[str]) -> tuple[str, str]:
    if not args: return "fa", ""
    first = args[0].lower().strip()
    if first in SUPPORTED_LANGS and len(first) == 2: return first, " ".join(args[1:])
    return "fa", " ".join(args)

async def cmd_translate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user: return
    user_id = update.effective_user.id

    now = time.time()
    if user_id in _last_translate_time and now - _last_translate_time[user_id] < _TRANSLATE_COOLDOWN:
        return await update.message.reply_text(with_signature(f"⏳ لطفاً {_TRANSLATE_COOLDOWN} ثانیه صبر کنید."), parse_mode="HTML")
    _last_translate_time[user_id] = now

    target_lang, text_to_translate = _parse_lang_and_text(context.args or [])
    if not text_to_translate.strip() and update.message.reply_to_message:
        replied = update.message.reply_to_message
        text_to_translate = replied.text or replied.caption or ""

    if not text_to_translate.strip():
        return await update.message.reply_text(
            "⚠️ <b>راهنمای ترجمه:</b>\n\n"
            "۱️⃣ روی یک پیام ریپلای کنید و بنویسید: <code>/translate en</code>\n"
            "۲️⃣ یا متن را مستقیم بفرستید: <code>/translate en Hello world</code>",
            parse_mode="HTML",
        )

    text_to_translate = text_to_translate.strip()[:1500]
    status_msg = await update.message.reply_text("⏳ در حال ترجمه...")
    try: await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception: pass

    try:
        ai_service = get_ai_service()
        translated_text = await ai_service.translate(text=text_to_translate, target_language=target_lang, user_id=user_id)

        if not translated_text or not translated_text.strip():
            return await status_msg.edit_text(with_signature("⚠️ ترجمه‌ای دریافت نشد."), parse_mode="HTML")

        if translated_text.startswith("🚨 خطای دقیق ترجمه"):
            return await status_msg.edit_text(translated_text, parse_mode="HTML")

        lang_display = SUPPORTED_LANGS.get(target_lang, target_lang)
        final_text = with_signature(f"🌐 <b>ترجمه به {lang_display}:</b>\n\n{html.escape(translated_text)}")

        try:
            await status_msg.edit_text(final_text, parse_mode="HTML")
        except BadRequest:
            clean_text = re.sub(r"<[^>]+>", "", final_text)
            await status_msg.edit_text(clean_text)

    except Exception as e:
        logger.error(f"Translation error: {e}", exc_info=True)
        await status_msg.edit_text(with_signature(f"🚨 خطای سیستم:\n<code>{str(e)[:300]}</code>"), parse_mode="HTML")
