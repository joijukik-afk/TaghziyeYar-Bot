"""ابزارهای امنیتی متمرکز (Rate Limit, Private Only)."""

import time
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from telegram.ext import ContextTypes
from app.config import get_settings

_user_last_message_time: dict[int, float] = {}
_last_cleanup = time.time()


def _cleanup_old_rate_limits():
    global _last_cleanup
    if time.time() - _last_cleanup < 3600:
        return
    now = time.time()
    to_remove = [uid for uid, ts in _user_last_message_time.items() if now - ts > 3600]
    for uid in to_remove:
        _user_last_message_time.pop(uid, None)
    _last_cleanup = now


def private_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat = update.effective_chat
        if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            deep_link = f"https://t.me/{context.bot.username}?start=private_setup"
            keyboard = [[InlineKeyboardButton("🔒 ورود به چت خصوصی", url=deep_link)]]
            if update.message:
                await update.message.reply_text(
                    "🛡️ برای حفظ ۱۰۰٪ حریم خصوصی، این بخش فقط در چت خصوصی کار می‌کند.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            elif update.callback_query:
                await update.callback_query.answer("لطفاً به چت خصوصی ربات بروید.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def rate_limited(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return await func(update, context, *args, **kwargs)

        _cleanup_old_rate_limits()
        user_id = update.effective_user.id
        current_time = time.time()
        settings = get_settings()

        if user_id in _user_last_message_time:
            if current_time - _user_last_message_time[user_id] < settings.rate_limit_seconds:
                return

        _user_last_message_time[user_id] = current_time
        return await func(update, context, *args, **kwargs)
    return wrapper
