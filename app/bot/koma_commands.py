"""KOMA Telegram commands — audio delivery with robust UX.

Changes vs 2.1:
    * FloodWait / RetryAfter handling (Telegram rate limits)
    * Memory cleanup for per-chat locks and per-user cooldowns
    * Structured logging at command entry/exit
    * CancelledError propagation (graceful shutdown)
    * Slightly better HTML safety on status messages

Kept intact:
    * /koma and /music flows
    * Per-chat lock + per-user cooldown
    * Safe status-message edit with plain-text fallback
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Dict

from telegram import Update, Message
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter
from telegram.ext import ContextTypes

from app.services.music_service import (
    fetch_and_send_music,
    fetch_and_send_custom_music,
)
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#  CONFIG
# ═══════════════════════════════════════════════════════════════════════

import os

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


MUSIC_COOLDOWN = _env_int("KOMA_USER_COOLDOWN", 10)
MAX_QUERY_DISPLAY = 30
_LOCK_CLEANUP_THRESHOLD = 500
_COOLDOWN_CLEANUP_THRESHOLD = 5000


# ═══════════════════════════════════════════════════════════════════════
#  STATE
# ═══════════════════════════════════════════════════════════════════════

_last_music_time: Dict[int, float] = {}
_chat_locks: Dict[int, asyncio.Lock] = {}


def _get_chat_lock(chat_id: int) -> asyncio.Lock:
    # Periodic cleanup of unlocked, unused locks
    if len(_chat_locks) > _LOCK_CLEANUP_THRESHOLD:
        stale = [
            cid for cid, lock in _chat_locks.items()
            if not lock.locked() and cid != chat_id
        ]
        for cid in stale:
            _chat_locks.pop(cid, None)
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]


def _cleanup_cooldowns() -> None:
    if len(_last_music_time) < _COOLDOWN_CLEANUP_THRESHOLD:
        return
    cutoff = time.time() - 300
    for uid in [u for u, t in _last_music_time.items() if t < cutoff]:
        _last_music_time.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════

async def _safe_edit(
    msg: Message, text: str, parse_mode: str = ParseMode.HTML,
) -> None:
    try:
        await msg.edit_text(text, parse_mode=parse_mode)
    except BadRequest:
        try:
            await msg.edit_text(re.sub(r"<[^>]+>", "", text))
        except Exception:
            pass
    except RetryAfter as e:
        try:
            await asyncio.sleep(e.retry_after)
            await msg.edit_text(
                re.sub(r"<[^>]+>", "", text),
            )
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
    _cleanup_cooldowns()
    return False


def _cooldown_message() -> str:
    return with_signature(f"⏳ لطفاً {MUSIC_COOLDOWN} ثانیه صبر کنید.")


def _locked_message() -> str:
    return with_signature(
        "⏳ لطفاً صبر کنید، درخواست قبلی در حال انجام است."
    )


def _display_query(query: str) -> str:
    if len(query) > MAX_QUERY_DISPLAY:
        return query[: MAX_QUERY_DISPLAY - 3] + "..."
    return query


# ═══════════════════════════════════════════════════════════════════════
#  /koma
# ═══════════════════════════════════════════════════════════════════════

async def cmd_koma(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_chat is None or update.message is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    thread_id = (
        update.message.message_thread_id
        if getattr(update.effective_chat, "is_forum", False)
        else None
    )

    if _rate_limited(user_id):
        await update.message.reply_text(
            _cooldown_message(), parse_mode=ParseMode.HTML,
        )
        return

    lock = _get_chat_lock(chat_id)
    if lock.locked():
        await update.message.reply_text(
            _locked_message(), parse_mode=ParseMode.HTML,
        )
        return

    async with lock:
        try:
            status_msg = await update.message.reply_text(
                "🎧 در حال جستجوی یک آهنگ جدید در ساندکلود..."
            )
        except Forbidden:
            logger.info(
                "cmd_koma: Forbidden for chat %s (bot removed?)", chat_id,
            )
            return
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                status_msg = await update.message.reply_text(
                    "🎧 در حال جستجو..."
                )
            except Exception:
                return
        except Exception as e:
            logger.warning("cmd_koma: reply failed: %s", e)
            return

        try:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.UPLOAD_VOICE,
            )
        except Exception:
            pass

        try:
            success = await fetch_and_send_music(
                context.bot, chat_id, thread_id=thread_id,
            )
            if success:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                logger.info(
                    "cmd_koma: success (chat=%s user=%s)",
                    chat_id, user_id,
                )
            else:
                await _safe_edit(
                    status_msg,
                    with_signature(
                        "❌ متأسفانه آهنگ **جدید** و تکرارنشده‌ای "
                        "در ساندکلود پیدا نشد. لطفاً چند دقیقه بعد "
                        "دوباره تلاش کنید."
                    ),
                )
                logger.info(
                    "cmd_koma: no track (chat=%s user=%s)",
                    chat_id, user_id,
                )
        except asyncio.CancelledError:
            logger.info("cmd_koma: cancelled")
            raise
        except Exception as e:
            logger.error(
                "cmd_koma error (chat=%s): %s", chat_id, e, exc_info=True,
            )
            await _safe_edit(
                status_msg,
                with_signature(
                    "⚠️ متأسفانه خطایی در ارتباط با ساندکلود رخ داد."
                ),
            )


# ═══════════════════════════════════════════════════════════════════════
#  /music
# ═══════════════════════════════════════════════════════════════════════

async def cmd_music(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.effective_chat is None or update.message is None:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0
    thread_id = (
        update.message.message_thread_id
        if getattr(update.effective_chat, "is_forum", False)
        else None
    )

    # Help when no args
    if not context.args:
        await update.message.reply_text(
            "📝 راهنمای دستور /music\n\n"
            "برای جستجو در ساندکلود، اسم آهنگ را بنویسید:\n"
            "`/music علی سورنا`\n\n"
            "برای دانلود از لینک ساندکلود:\n"
            "`/music https://soundcloud.com/...`",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    if _rate_limited(user_id):
        await update.message.reply_text(
            _cooldown_message(), parse_mode=ParseMode.HTML,
        )
        return

    query = " ".join(context.args).strip()
    display_query = _display_query(query)

    lock = _get_chat_lock(chat_id)
    if lock.locked():
        await update.message.reply_text(
            _locked_message(), parse_mode=ParseMode.HTML,
        )
        return

    async with lock:
        try:
            status_msg = await update.message.reply_text(
                f"🔎 در حال جستجو برای: {display_query}"
            )
        except Forbidden:
            logger.info(
                "cmd_music: Forbidden for chat %s", chat_id,
            )
            return
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                status_msg = await update.message.reply_text(
                    f"🔎 در حال جستجو برای: {display_query}"
                )
            except Exception:
                return
        except Exception as e:
            logger.warning("cmd_music: reply failed: %s", e)
            return

        try:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.UPLOAD_VOICE,
            )
        except Exception:
            pass

        try:
            success = await fetch_and_send_custom_music(
                context.bot, chat_id, query, thread_id=thread_id,
            )
            if success:
                try:
                    await status_msg.delete()
                except Exception:
                    pass
                logger.info(
                    "cmd_music: success (chat=%s query=%r)",
                    chat_id, query[:50],
                )
            else:
                await _safe_edit(
                    status_msg,
                    with_signature(
                        "❌ متأسفانه آهنگی با این اسم پیدا نشد "
                        "یا قبلاً ارسال شده است."
                    ),
                )
                logger.info(
                    "cmd_music: no result (chat=%s query=%r)",
                    chat_id, query[:50],
                )
        except asyncio.CancelledError:
            logger.info("cmd_music: cancelled")
            raise
        except Exception as e:
            logger.error(
                "cmd_music error (chat=%s): %s", chat_id, e, exc_info=True,
            )
            await _safe_edit(
                status_msg,
                with_signature(
                    "⚠️ متأسفانه خطایی رخ داد. لطفاً بعداً تلاش کنید."
                ),
            )
