"""KOMA Telegram commands.

- /koma        → strict KOMA discovery, returns ONE official link
- /music <q>   → general search, returns official link

Design notes:
    * No audio files are downloaded or redistributed.
    * Every successful result returns the official SoundCloud URL.
    * All UX messages are Persian, HTML-safe, and rate-limited.
    * Per-chat lock prevents concurrent searches within the same chat.
    * Failed attempts never lower the KOMA threshold.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from typing import Dict, Optional

from telegram import Update, Message
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from app.services.music_service import (
    CFG,
    discover_koma_track,
    discover_specific_song,
    is_artist_in_cooldown,
    is_title_duplicate,
    record_send,
    resolve_track_url,
    score_track,
    was_sent,
)
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

# Cooldown / locks (in-memory, short-lived)
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


def _esc(s: str) -> str:
    return html.escape(str(s or ""), quote=False)


async def _send_koma_result(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    thread_id: Optional[int],
    selection,
) -> None:
    """Send the chosen KOMA track as an attributed link."""
    c = selection.candidate
    score = selection.score
    title = _esc(c.title)
    artist = _esc(c.artist)
    url = c.url

    caption = (
        f"🖤 <b>KOMA — کشف جدید</b>\n\n"
        f"🎵 <b>{title}</b>\n"
        f"🎤 {artist}\n"
        f"⭐ امتیاز KOMA: <b>{score}/100</b>\n"
    )
    if c.duration:
        mins, secs = divmod(c.duration, 60)
        caption += f"⏱ مدت: {mins}:{secs:02d}\n"
    if c.upload_date:
        caption += f"📅 انتشار: {c.upload_date[:4]}-{c.upload_date[4:6]}-{c.upload_date[6:8]}\n"
    caption += (
        f"\n🔗 <a href=\"{_esc(url)}\">گوش دادن در SoundCloud</a>\n\n"
        f"<i>این آهنگ از طریق متادیتای عمومی SoundCloud کشف شد. "
        f"تمام حقوق متعلق به سازنده اصلی است.</i>"
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text=with_signature(caption),
        parse_mode=ParseMode.HTML,
        message_thread_id=thread_id,
        disable_web_page_preview=False,
    )

    # Persist AFTER a successful send
    try:
        await record_send(
            identifier=c.sc_id,
            title=c.title,
            artist=c.artist,
            url=c.url,
        )
    except Exception as exc:
        logger.warning("Failed to persist KOMA send: %s", exc)


# ═══════════════════════════════════════════════════════════════════════
#  /koma
# ═══════════════════════════════════════════════════════════════════════

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
            with_signature(
                f"⏳ لطفاً {CFG.user_cooldown_seconds} ثانیه صبر کنید."
            ),
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
                "🖤 KOMA در حال جستجوی یک آهنگ جدید...\n"
                "<i>در حال بررسی چندین منبع و امتیازدهی</i>",
                parse_mode=ParseMode.HTML,
            )
        except Forbidden:
            return

        try:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.TYPING,
            )
        except Exception:
            pass

        try:
            selection = await discover_koma_track()
        except Exception as exc:
            logger.error("cmd_koma discover failed: %s", exc, exc_info=True)
            await _safe_edit(
                status,
                with_signature(
                    "⚠️ خطا در ارتباط با SoundCloud. لطفاً بعداً تلاش کنید."
                ),
            )
            return

        if selection is None:
            await _safe_edit(
                status,
                with_signature(
                    "❌ در این دور آهنگ **جدید** و کاملاً منطبق با KOMA "
                    "پیدا نشد.\n\n"
                    "🎯 KOMA آهنگ تصادفی نمی‌فرستد. آستانه‌ی کیفیت "
                    f"({CFG.min_score}/100) پایین آورده نمی‌شود.\n"
                    "⏱ چند دقیقه بعد دوباره امتحان کنید."
                ),
            )
            return

        try:
            await _send_koma_result(context, chat_id, thread_id, selection)
            try:
                await status.delete()
            except Exception:
                pass
            logger.info(
                "KOMA sent: %r by %r (score=%d)",
                selection.candidate.title,
                selection.candidate.artist,
                selection.score,
            )
        except Exception as exc:
            logger.error("cmd_koma send failed: %s", exc, exc_info=True)
            await _safe_edit(
                status,
                with_signature(
                    "⚠️ خطا در ارسال نتیجه. لطفاً بعداً تلاش کنید."
                ),
            )


# ═══════════════════════════════════════════════════════════════════════
#  /music
# ═══════════════════════════════════════════════════════════════════════

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

    # No argument → help
    if not context.args:
        await update.message.reply_text(
            with_signature(
                "📝 <b>راهنمای /music</b>\n\n"
                "🔎 جستجو با نام:\n"
                "<code>/music song name</code>\n\n"
                "🔗 ارسال از لینک SoundCloud:\n"
                "<code>/music https://soundcloud.com/...</code>"
            ),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    if _user_cooldown(user_id):
        await update.message.reply_text(
            with_signature(
                f"⏳ لطفاً {CFG.user_cooldown_seconds} ثانیه صبر کنید."
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    query = " ".join(context.args).strip()
    is_url = query.startswith(("http://", "https://"))

    lock = _get_chat_lock(chat_id)
    if lock.locked():
        await update.message.reply_text(
            with_signature("⏳ درخواست قبلی در حال انجام است."),
            parse_mode=ParseMode.HTML,
        )
        return

    async with lock:
        display = query if len(query) <= 40 else query[:37] + "..."
        try:
            status = await update.message.reply_text(
                f"🔎 در حال جستجو: {_esc(display)}",
                parse_mode=ParseMode.HTML,
            )
        except Forbidden:
            return

        try:
            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.TYPING,
            )
        except Exception:
            pass

        try:
            if is_url:
                candidate = await resolve_track_url(query)
                if not candidate:
                    await _safe_edit(
                        status,
                        with_signature("❌ لینک معتبر SoundCloud نبود."),
                    )
                    return
                if await was_sent(candidate.sc_id):
                    await _safe_edit(
                        status,
                        with_signature("❌ این آهنگ قبلاً ارسال شده است."),
                    )
                    return
            else:
                candidate = await discover_specific_song(query)
                if not candidate:
                    await _safe_edit(
                        status,
                        with_signature(
                            "❌ آهنگی با این نام پیدا نشد."
                        ),
                    )
                    return

            # Send as link
            title = _esc(candidate.title)
            artist = _esc(candidate.artist)
            url = _esc(candidate.url)
            text = with_signature(
                f"🎵 <b>{title}</b>\n"
                f"🎤 {artist}\n\n"
                f"🔗 <a href=\"{url}\">گوش دادن در SoundCloud</a>\n\n"
                f"<i>این آهنگ از طریق متادیتای عمومی SoundCloud پیدا شد. "
                f"تمام حقوق متعلق به سازنده اصلی است.</i>"
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                message_thread_id=thread_id,
                disable_web_page_preview=False,
            )
            try:
                await status.delete()
            except Exception:
                pass

            try:
                await record_send(
                    identifier=candidate.sc_id,
                    title=candidate.title,
                    artist=candidate.artist,
                    url=candidate.url,
                )
            except Exception:
                pass

        except Exception as exc:
            logger.error("cmd_music failed: %s", exc, exc_info=True)
            await _safe_edit(
                status,
                with_signature("⚠️ خطایی رخ داد. لطفاً بعداً تلاش کنید."),
            )
