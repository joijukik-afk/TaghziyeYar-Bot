"""دستورات موزیک KOMA (با مدیریت خطای شبکه)"""

import logging
import time
import asyncio
import re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest, Forbidden, NetworkError
import app.services.music_service as ms
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

_MUSIC_COOLDOWN = 5
_last_music_time: dict[int, float] = {}
_chat_locks: dict[int, asyncio.Lock] = {}

def _get_chat_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]

async def _safe_edit(msg, text: str, parse_mode: str = "HTML"):
    try:
        await msg.edit_text(text, parse_mode=parse_mode)
    except (BadRequest, NetworkError):
        clean = re.sub(r"<[^>]+>", "", text)
        try: await msg.edit_text(clean)
        except Exception: pass
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
            status_msg = await update.message.reply_text("🎧 در حال جستجو...")
        except (Forbidden, NetworkError):
            return

        try:
            success = await ms.fetch_and_send_music(context.bot, chat_id, thread_id=thread_id)
            if success:
                try: await status_msg.delete()
                except Exception: pass
            else:
                error_text = f"❌ خطای دیباگ (Koma):\n<code>{ms.LAST_ERROR}</code>"
                await _safe_edit(status_msg, with_signature(error_text))
        except Exception as e:
            await _safe_edit(status_msg, with_signature(f"⚠️ خطای داخلی: <code>{str(e)}</code>"))

async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None: return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    thread_id = update.message.message_thread_id if update.effective_chat.is_forum else None

    if not context.args:
        return await update.message.reply_text("🎵 <code>/music نام آهنگ</code>", parse_mode="HTML")

    now = time.time()
    if user_id in _last_music_time and now - _last_music_time[user_id] < _MUSIC_COOLDOWN:
        return await update.message.reply_text(with_signature(f"⏳ لطفاً {_MUSIC_COOLDOWN} ثانیه صبر کنید."), parse_mode="HTML")
    _last_music_time[user_id] = now

    query = " ".join(context.args).strip()
    lock = _get_chat_lock(chat_id)
    
    if lock.locked():
        return await update.message.reply_text(with_signature("⏳ لطفاً صبر کنید، درخواست قبلی در حال انجام است."), parse_mode="HTML")

    async with lock:
        try:
            status_msg = await update.message.reply_text(f"🔍 در حال جستجو برای: {query}")
        except (Forbidden, NetworkError):
            return

        try:
            success = await ms.fetch_and_send_custom_music(context.bot, chat_id, query, thread_id=thread_id)
            if success:
                try: await status_msg.delete()
                except Exception: pass
            else:
                error_text = f"❌ خطای دیباگ (Music):\n<code>{ms.LAST_ERROR}</code>"
                await _safe_edit(status_msg, with_signature(error_text))
        except Exception as e:
            await _safe_edit(status_msg, with_signature(f"⚠️ خطای داخلی: <code>{str(e)}</code>"))
