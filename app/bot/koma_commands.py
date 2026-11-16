"""دستورات موزیک KOMA (بدون آرشیو)"""

import logging
import time
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden
from app.services.music_service import fetch_and_send_music, fetch_and_send_custom_music
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

_MUSIC_COOLDOWN = 10
_last_music_time: dict[int, float] = {}
_chat_locks: dict[int, asyncio.Lock] = {}

def _get_chat_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]

async def _safe_edit(msg, text: str, parse_mode: str = "HTML"):
    try:
        await msg.edit_text(text, parse_mode=parse_mode)
    except BadRequest:
        import re
        clean = re.sub(r"<[^>]+>", "", text)
        try: await msg.edit_text(clean)
        except Exception: pass

async def cmd_koma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None: return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    thread_id = update.message.message_thread_id if update.effective_chat.is_forum else None

    now = time.time()
    if user_id in _last_music_time and now - _last_music_time[user_id] < _MUSIC_COOLDOWN:
        return await update.message.reply_text(with_signature(f"⏳ لطفاً {_MUSIC_COOLDOWN} ثانیه صبر کنید."), parse_mode="HTML")
    _last_music_time[user_id] = now

    lock = _get_chat_lock(chat_id)
    if lock.locked():
        return await update.message.reply_text(with_signature("⏳ لطفاً صبر کنید، درخواست قبلی در حال انجام است."), parse_mode="HTML")

    async with lock:
        try:
            status_msg = await update.message.reply_text("🎧 در حال جستجوی یک آهنگ جدید در ساندکلود...")
        except Forbidden:
            return

        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_audio")
        except Exception: pass

        try:
            success = await fetch_and_send_music(context.bot, chat_id, thread_id=thread_id)
            if success:
                try: await status_msg.delete()
                except Exception: pass
            else:
                await _safe_edit(status_msg, with_signature("❌ متأسفانه آهنگ **جدید** و تکراری‌نشده‌ای در ساندکلود پیدا نشد. لطفاً چند دقیقه بعد دوباره تلاش کنید."))
        except Exception as e:
            logger.error(f"cmd_koma error: {e}", exc_info=True)
            await _safe_edit(status_msg, with_signature("⚠️ متأسفانه خطایی در ارتباط با ساندکلود رخ داد."))


async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None: return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    thread_id = update.message.message_thread_id if update.effective_chat.is_forum else None

    if not context.args:
        return await update.message.reply_text(
            "🎵 <b>راهنمای دستور /music</b>\n\n"
            "برای جستجو در ساندکلود، اسم آهنگ رو بنویس:\n"
            "<code>/music علی سورنا</code>\n\n"
            "برای دانلود از لینک ساندکلود:\n"
            "<code>/music https://soundcloud.com/...</code>",
            parse_mode="HTML",
        )

    now = time.time()
    if user_id in _last_music_time and now - _last_music_time[user_id] < _MUSIC_COOLDOWN:
        return await update.message.reply_text(with_signature(f"⏳ لطفاً {_MUSIC_COOLDOWN} ثانیه صبر کنید."), parse_mode="HTML")
    _last_music_time[user_id] = now

    query = " ".join(context.args).strip()
    display_query = (query[:27] + "...") if len(query) > 30 else query

    lock = _get_chat_lock(chat_id)
    if lock.locked():
        return await update.message.reply_text(with_signature("⏳ لطفاً صبر کنید، درخواست قبلی در حال انجام است."), parse_mode="HTML")

    async with lock:
        try:
            status_msg = await update.message.reply_text(f"🔍 در حال جستجو برای: {display_query}")
        except Forbidden:
            return

        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_audio")
        except Exception: pass

        try:
            success = await fetch_and_send_custom_music(context.bot, chat_id, query, thread_id=thread_id)
            if success:
                try: await status_msg.delete()
                except Exception: pass
            else:
                await _safe_edit(status_msg, with_signature("❌ متأسفانه آهنگی با این اسم پیدا نشد یا قبلاً ارسال شده است."))
        except Exception as e:
            logger.error(f"cmd_music error: {e}", exc_info=True)
            await _safe_edit(status_msg, with_signature("⚠️ متأسفانه خطایی رخ داد. لطفاً بعداً تلاش کنید."))
