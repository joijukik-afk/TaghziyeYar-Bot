"""دستور /koma برای دریافت یک آهنگ واقعی از Internet Archive"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from app.services.music_service import fetch_and_send_music

logger = logging.getLogger(__name__)

# قفل ضد اسپم (هر چت فقط یک درخواست در هر لحظه می‌تونه بفرسته)
_chat_locks = set()


async def cmd_koma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None:
        return

    chat_id = update.effective_chat.id

    # چک کردن اینکه آیا همون لحظه درخواست دیگه‌ای در جریانه یا نه
    if chat_id in _chat_locks:
        await update.message.reply_text("⏳ یک آهنگ دیگر در حال آماده‌سازی است، لطفاً صبر کنید...")
        return

    _chat_locks.add(chat_id)
    status_msg = None

    try:
        # ارسال پیام انتظار
        status_msg = await update.message.reply_text("🎧 در حال جستجوی آهنگ جدید...")

        # صدا زدن سرویس اصلی (که در قدم دوم ساختیم)
        success = await fetch_and_send_music(context.bot, chat_id, status_msg)

        if success:
            # اگر آهنگ با موفقیت ارسال شد، پیام "در حال جستجو" رو پاک میکنیم
            try:
                await status_msg.delete()
            except Exception:
                pass
        else:
            # اگر آهنگی پیدا نشد یا خطا داد
            await status_msg.edit_text(
                "❌ متأسفانه آهنگ جدید و قابل ارسالی پیدا نشد.\n"
                "لطفاً چند دقیقه بعد دوباره امتحان کنید."
            )
    except Exception as e:
        logger.error(f"cmd_koma error: {e}", exc_info=True)
        try:
            if status_msg:
                await status_msg.edit_text("⚠️ خطایی رخ داد، دوباره تلاش کنید.")
        except Exception:
            pass
    finally:
        # آزاد کردن قفل تا دفعه بعد بتونه آهنگ بفرسته
        _chat_locks.discard(chat_id)
