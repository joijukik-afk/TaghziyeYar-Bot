"""دستور /koma برای دریافت یک آهنگ واقعی از یوتیوب"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from app.services.music_service import fetch_and_send_music

logger = logging.getLogger(__name__)
_chat_locks = set()

async def cmd_koma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None: return
    chat_id = update.effective_chat.id

    if chat_id in _chat_locks:
        await update.message.reply_text("⏳ یک آهنگ دیگر در حال آماده‌سازی است...")
        return

    _chat_locks.add(chat_id)
    status_msg = await update.message.reply_text("🎧 در حال جستجو و دانلود از یوتیوب...")

    try:
        success = await fetch_and_send_music(context.bot, chat_id, status_msg)
        if success:
            try: await status_msg.delete()
            except: pass
        else:
            await status_msg.edit_text("❌ متأسفانه آهنگ پیدا نشد یا یوتیوب اجازه دانلود نداد.")
    except Exception as e:
        logger.error(f"cmd_koma error: {e}")
        await status_msg.edit_text("⚠️ خطایی رخ داد، دوباره تلاش کنید.")
    finally:
        _chat_locks.discard(chat_id)
