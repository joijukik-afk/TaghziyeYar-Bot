"""دستورات موزیک (koma برای تصادفی، music برای جستجوی دستی)"""

import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden
from app.services.music_service import fetch_and_send_music, fetch_and_send_custom_music

logger = logging.getLogger(__name__)
_chat_locks = set()

# 👇 دستور /koma (همون قبلی برای دریافت تصادفی)
async def cmd_koma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None: return
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.effective_chat.is_forum else None

    if chat_id in _chat_locks:
        return await update.message.reply_text("⏳ لطفاً صبر کنید...")
    _chat_locks.add(chat_id)
    
    try:
        status_msg = await update.message.reply_text("🎧 در حال جستجو در آرشیو KOMA (تصادفی)...")
    except Forbidden:
        _chat_locks.discard(chat_id); return 

    try:
        success = await fetch_and_send_music(context.bot, chat_id, thread_id=thread_id)
        if success:
            try: await status_msg.delete()
            except: pass
        else:
            await status_msg.edit_text("❌ آهنگ پیدا نشد.")
    except Exception as e:
        await status_msg.edit_text("⚠️ خطایی رخ داد.")
    finally:
        _chat_locks.discard(chat_id)


# 👇 دستور جدید /music (جستجو با اسم یا لینک)
async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None: return
    chat_id = update.effective_chat.id
    thread_id = update.message.message_thread_id if update.effective_chat.is_forum else None

    # چک کردن اینکه کاربر چیزی نوشته یا نه
    if not context.args:
        return await update.message.reply_text(
            "🎵 **راهنمای دستور /music**\n\n"
            "برای جستجو، اسم آهنگ رو بنویس:\n"
            "`/music علی سورنا`\n\n"
            "برای دانلود از لینک (یوتیوب، ساندکلود و...):\n"
            "`/music https://youtu.be/...`",
            parse_mode="Markdown"
        )

    query = " ".join(context.args).strip()

    if chat_id in _chat_locks:
        return await update.message.reply_text("⏳ لطفاً صبر کنید، درخواست قبلی در حال انجام است.")
    _chat_locks.add(chat_id)
    
    try:
        status_msg = await update.message.reply_text(f"🔍 در حال جستجو برای: {query[:30]}...")
    except Forbidden:
        _chat_locks.discard(chat_id); return 

    try:
        success = await fetch_and_send_custom_music(context.bot, chat_id, query, thread_id=thread_id)
        if success:
            try: await status_msg.delete()
            except: pass
        else:
            await status_msg.edit_text("❌ متأسفانه آهنگی با این اسم یا لینک پیدا نشد.")
    except Exception as e:
        logger.error(f"cmd_music error: {e}")
        await status_msg.edit_text("⚠️ خطایی رخ داد.")
    finally:
        _chat_locks.discard(chat_id)
