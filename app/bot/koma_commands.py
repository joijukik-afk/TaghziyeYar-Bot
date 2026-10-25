"""دستور /koma برای دریافت آهنگ از موتور جستجوی چندمنبعی KOMA"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from app.services.music_service import fetch_and_send_music

logger = logging.getLogger(__name__)
_chat_locks = set()

async def cmd_koma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None: return
    chat_id = update.effective_chat.id

    # جلوگیری از زدن همزمان دستور
    if chat_id in _chat_locks:
        await update.message.reply_text("⏳ لطفاً صبر کنید، در حال آماده‌سازی آهنگ بعدی...")
        return

    _chat_locks.add(chat_id)
    status_msg = await update.message.reply_text("🎧 در حال جستجو در آرشیو KOMA (YouTube, SoundCloud, Archive)...")

    try:
        success = await fetch_and_send_music(context.bot, chat_id)
        if success:
            try: await status_msg.delete()
            except: pass
        else:
            await status_msg.edit_text(
                "❌ متأسفانه آهنگ جدیدی پیدا نشد یا منابع اجازه دانلود ندادند.\n"
                "لطفاً چند دقیقه دیگر دوباره تلاش کنید."
            )
    except Exception as e:
        logger.error(f"cmd_koma error: {e}")
        await status_msg.edit_text("⚠️ خطایی رخ داد. لطفاً دوباره تلاش کنید.")
    finally:
        _chat_locks.discard(chat_id)
