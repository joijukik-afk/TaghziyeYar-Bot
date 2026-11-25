"""KOMA Telegram commands — sends actual audio files."""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Dict

from telegram import Update, Message
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from app.services.music_service import (
    CFG,
    fetch_and_send_music,
    fetch_and_send_custom_music,
)
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

_last_request: Dict[int, float] = {}
_chat_locks: Dict[int, asyncio.Lock] = {}


def _get_chat_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _chat_locks:
        _chat_locks[chat_id] = asyncio.Lock()
    return _chat_locks[chat_id]


def _user_cooldown(user_id: int) -> bool:
    now = time.time()
    last = _last_request.get(user_id, 0.0)
    if now - last < CFG.user_cooldown_seconds:
        return True
    _last_request[user_id] = now
    return False


async def _safe_edit(msg: Message, text: str, parse_mode: str = ParseMode.HTML) -> None:
    try:
        await msg.edit_text(text, parse_mode=parse_mode)
    except BadRequest:
        try:
            await msg.edit_text(re.sub(r"<[^>]+>", "", text))
        except Exception:
            pass
    except Exception:
        pass


async def cmd_koma(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    thread_id = (
        update.message.message_thread_id
        if getattr(update.effective_chat, "is_forum", False)
        else None
    )

    if _user_cooldown(user_id):
        await update.message.reply_text(
            with_signature(f"⏳ لطفاً {CFG.user_cooldown_seconds} ثانیه صبر کنید."),
            parse_mode=ParseMode.HTML,
        )
        return

    lock = _get_chat_lock(chat_id)
    if lock.locked():
        await update.message.reply_text(
            with_signature("⏳ درخواست قبلی در حال انجام است."),
            parse_mode=ParseMode.HTML,
        )
        return

    async with lock:
        try:
            status = await update.message.reply_text(
                "🖤 KOMA در حال جستجو...\n<i>چند ثانیه صبر کنید</i>",
                parse_mode=ParseMode.HTML,
            )
        except Forbidden:
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
                    await status.delete()
                except Exception:
                    pass
            else:
                await _safe_edit(
                    status,
                    with_signature(
                        "❌ در این دور آهنگ **جدید** و مناسبی پیدا نشد.\n\n"
                        "💡 این معمولاً یعنی همه‌ی گزینه‌های خوب قبلاً ارسال شدن "
                        "یا آرتیست‌هاشون توی cooldown هستن.\n\n"
                        "⏱ چند دقیقه دیگه دوباره امتحان کنید."
                    ),
                )
        except Exception as exc:
            logger.error("cmd_koma error: %s", exc, exc_info=True)
            await _safe_edit(
                status,
                with_signature("⚠️ خطایی در ارتباط با SoundCloud رخ داد."),
            )


async def cmd_music(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_chat or not update.effective_user:
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    thread_id = (
        update.message.message_thread_id
        if getattr(update.effective_chat, "is_forum", False)
        else None
    )

    if not context.args:
        await update.message.reply_text(
            with_signature(
                "📝 <b>راهنمای /music</b>\n\n"
                "🔎 جستجو:\n<code>/music song name</code>\n\n"
                "🔗 لینک SoundCloud:\n<code>/music https://soundcloud.com/...</code>"
            ),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    if _user_cooldown(user_id):
        await update.message.reply_text(
            with_signature(f"⏳ لطفاً {CFG.user_cooldown_seconds} ثانیه صبر کنید."),
            parse_mode=ParseMode.HTML,
        )
        return

    query = " ".join(context.args).strip()
    display = query if len(query) <= 40 else query[:37] + "..."

    lock = _get_chat_lock(chat_id)
    if lock.locked():
        await update.message.reply_text(
            with_signature("⏳ درخواست قبلی در حال انجام است."),
            parse_mode=ParseMode.HTML,
        )
        return

    async with lock:
        try:
            status = await update.message.reply_text(
                f"🔎 در حال جستجو: {display}",
                parse_mode=ParseMode.HTML,
            )
        except Forbidden:
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
                    await status.delete()
                except Exception:
                    pass
            else:
                await _safe_edit(
                    status,
                    with_signature(
                        "❌ آهنگی با این اسم پیدا نشد یا قبلاً ارسال شده است."
                    ),
                )
        except Exception as exc:
            logger.error("cmd_music error: %s", exc, exc_info=True)
            await _safe_edit(
                status,
                with_signature("⚠️ خطایی رخ داد. لطفاً بعداً تلاش کنید."),
            )
