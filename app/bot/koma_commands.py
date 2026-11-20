"""دستورات موزیک KOMA (بدون آرشیو)

دستورات:
- /koma  → جستجوی هوشمند و ارسال یک آهنگ جدید
- /music <query>  → جستجوی دقیق یا ارسال از لینک SoundCloud

ویژگی‌ها:
- Rate limit سراسری و per-chat lock
- پیام وضعیت با ویرایش ایمن (fallback در صورت خطای HTML)
- مدیریت خطاهای Forbidden / BadRequest / شبکه
- سازگار با نسخه 2.0 سرویس موسیقی
"""
import asyncio
import logging
import re
import time
from typing import Optional

from telegram import Update, Message
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from app.services.music_service import (
    fetch_and_send_music,
    fetch_and_send_custom_music,
)
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

# ==================== تنظیمات ====================
MUSIC_COOLDOWN = 10          # ثانیه بین دو درخواست از یک کاربر
MAX_QUERY_DISPLAY = 30       # حداکثر طول نمایش کوئری در پیام وضعیت

# ==================== وضعیت in-memory ====================
_last_music_time: dict[int, float] = {}
_chat_locks: dict[int, asyncio.Lock] = {}


def _get_chat_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]


# ==================== ابزارهای کمکی ====================
async def _safe_edit(msg: Message, text: str, parse_mode: str = ParseMode.HTML) -> None:
    """ویرایش پیام با fallback در صورت خطای پارس HTML"""
    try:
        await msg.edit_text(text, parse_mode=parse_mode)
    except BadRequest:
        clean = re.sub(r"<[^>]+>", "", text)
        try:
            await msg.edit_text(clean)
        except Exception:
            pass
    except Exception:
        pass


def _rate_limited(user_id: int) -> bool:
    now = time.time()
    last = _last_music_time.get(user_id, 0)
    if now - last < MUSIC_COOLDOWN:
        return True
    _last_music_time[user_id] = now
    return False


def _cooldown_message() -> str:
    return with_signature(f"⏳ لطفاً {MUSIC_COOLDOWN} ثانیه صبر کنید.")


def _locked_message() -> str:
    return with_signature("⏳ لطفاً صبر کنید، درخواست قبلی در حال انجام است.")


def _display_query(query: str) -> str:
    if len(query) > MAX_QUERY_DISPLAY:
        return query[: MAX_QUERY_DISPLAY - 3] + "..."
    return query


# ==================== دستور /koma ====================
async def cmd_koma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    thread_id = (
        update.message.message_thread_id
        if update.effective_chat.is_forum
        else None
    )

    if _rate_limited(user_id):
        await update.message.reply_text(
            _cooldown_message(), parse_mode=ParseMode.HTML
        )
        return

    lock = _get_chat_lock(chat_id)
    if lock.locked():
        await update.message.reply_text(
            _locked_message(), parse_mode=ParseMode.HTML
        )
        return

    async with lock:
        try:
            status_msg = await update.message.reply_text(
                "🎧 در حال جستجوی یک آهنگ جدید در ساندکلود..."
            )
        except Forbidden:
            return

        try:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.UPLOAD_VOICE
            )
        except Exception:
            pass

        try:
            success = await fetch_and_send_music(
                context.bot, chat_id, thread_id=thread_id
            )
            if success:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            else:
                await _safe_edit(
                    status_msg,
                    with_signature(
                        "❌ متأسفانه آهنگ **جدید** و تکرارنشده‌ای "
                        "در ساندکلود پیدا نشد. لطفاً چند دقیقه بعد دوباره تلاش کنید."
                    ),
                )
        except Exception as e:
            logger.error(f"cmd_koma error: {e}", exc_info=True)
            await _safe_edit(
                status_msg,
                with_signature(
                    "⚠️ متأسفانه خطایی در ارتباط با ساندکلود رخ داد."
                ),
            )


# ==================== دستور /music ====================
async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.message is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    thread_id = (
        update.message.message_thread_id
        if update.effective_chat.is_forum
        else None
    )

    # راهنما در صورت نبود آرگومان
    if not context.args:
        await update.message.reply_text(
            "📝 راهنمای دستور /music\n\n"
            "برای جستجو در ساندکلود، اسم آهنگ را بنویسید:\n"
            "`/music علی سورنا`\n\n"
            "برای دانلود از لینک ساندکلود:\n"
            "`/music https://soundcloud.com/...`",
            parse_mode=ParseMode.HTML,
        )
        return

    if _rate_limited(user_id):
        await update.message.reply_text(
            _cooldown_message(), parse_mode=ParseMode.HTML
        )
        return

    query = " ".join(context.args).strip()
    display_query = _display_query(query)

    lock = _get_chat_lock(chat_id)
    if lock.locked():
        await update.message.reply_text(
            _locked_message(), parse_mode=ParseMode.HTML
        )
        return

    async with lock:
        try:
            status_msg = await update.message.reply_text(
                f"🔎 در حال جستجو برای: {display_query}"
            )
        except Forbidden:
            return

        try:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.UPLOAD_VOICE
            )
        except Exception:
            pass

        try:
            success = await fetch_and_send_custom_music(
                context.bot, chat_id, query, thread_id=thread_id
            )
            if success:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
            else:
                await _safe_edit(
                    status_msg,
                    with_signature(
                        "❌ متأسفانه آهنگی با این اسم پیدا نشد "
                        "یا قبلاً ارسال شده است."
                    ),
                )
        except Exception as e:
            logger.error(f"cmd_music error: {e}", exc_info=True)
            await _safe_edit(
                status_msg,
                with_signature(
                    "⚠️ متأسفانه خطایی رخ داد. لطفاً بعداً تلاش کنید."
                ),
            )
