"""دستورات موزیک (koma برای کشف هوشمند، music برای دانلود) - مقاوم در برابر قطعی شبکه"""

import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import Forbidden, NetworkError
from app.services.music_service import fetch_and_send_music, fetch_and_send_custom_music

logger = logging.getLogger(__name__)
_chat_locks = set()

async def cmd_koma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None: return
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.effective_chat.is_forum else None

    if chat_id in _chat_locks:
        return await update.message.reply_text("⏳ لطفاً صبر کنید...")
    _chat_locks.add(chat_id)
    
    try:
        status_msg = await update.message.reply_text("🎧 در حال کشف موسیقی...")
    except (Forbidden, NetworkError) as e:
        logger.warning(f"Network error on /koma start: {e}")
        _chat_locks.discard(chat_id)
        return 

    try:
        success = await asyncio.wait_for(fetch_and_send_music(context.bot, chat_id, thread_id=thread_id), timeout=60.0)
        if success:
            try: await status_msg.delete()
            except Exception: pass
        else:
            try: await status_msg.edit_text("❌ آهنگ جدیدی پیدا نشد. دوباره تلاش کنید.")
            except Exception: pass
    except asyncio.TimeoutError:
        try: await status_msg.edit_text("⏱️ جستجو طول کشید و متوقف شد.")
        except Exception: pass
    except Exception as e:
        logger.error(f"cmd_koma error: {e}")
        try: await status_msg.edit_text("⚠️ خطایی رخ داد.")
        except Exception: pass
    finally:
        _chat_locks.discard(chat_id)


async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None: return
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.effective_chat.is_forum else None

    if not context.args:
        try:
            await update.message.reply_text(
                "🎵 **راهنمای دستور /music**\n\n"
                "`/music øneheart`\n"
                "`/music https://soundcloud.com/...`",
                parse_mode="Markdown"
            )
        except Exception: pass
        return

    query = " ".join(context.args).strip()

    if chat_id in _chat_locks:
        try: await update.message.reply_text("⏳ لطفاً صبر کنید...")
        except Exception: pass
        return
        
    _chat_locks.add(chat_id)
    
    try:
        status_msg = await update.message.reply_text(f"🔍 در حال جستجو و دانلود: {query[:30]}...")
    except (Forbidden, NetworkError) as e:
        logger.warning(f"Network error on /music start: {e}")
        _chat_locks.discard(chat_id)
        return 

    try:
        success, error_msg = await asyncio.wait_for(
            fetch_and_send_custom_music(context.bot, chat_id, query, thread_id=thread_id),
            timeout=60.0
        )
        
        if success:
            try: await status_msg.delete()
            except Exception: pass
        else:
            try:
                await status_msg.edit_text(f"❌ دانلود ناموفق بود.\n\n💡 <b>علت:</b>\n{error_msg}", parse_mode="HTML")
            except Exception: pass
            
    except asyncio.TimeoutError:
        try: await status_msg.edit_text("⏱️ دانلود بیش از ۶۰ ثانیه طول کشید و متوقف شد.")
        except Exception: pass
    except Exception as e:
        logger.error(f"cmd_music error: {e}")
        try: await status_msg.edit_text(f"⚠️ خطا: {str(e)[:100]}")
        except Exception: pass
    finally:
        _chat_locks.discard(chat_id)
