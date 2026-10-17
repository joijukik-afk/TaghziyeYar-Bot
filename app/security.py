"""ابزارهای امنیتی برای جلوگیری از لو رفتن اطلاعات و اسپم در گروه‌ها"""

import time
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

# دیکشنری برای جلوگیری از اسپم
_user_last_message_time = {}

def private_only(func):
    """
    دکوراتور امنیتی: دستورات حساس را فقط در چت خصوصی اجرا می‌کند.
    اگر در گروه زده شود، دکمه هدایت به پی وی می‌فرستد.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        # بررسی اینکه آیا در گروه هستیم
        if update.effective_chat and update.effective_chat.type in ("group", "supergroup"):
            bot_username = context.bot.username
            deep_link = f"https://t.me/{bot_username}?start=private_setup"
            keyboard = [[InlineKeyboardButton("🔒 ورود به چت خصوصی", url=deep_link)]]
            
            if update.message:
                await update.message.reply_text(
                    "🛡️ برای حفظ ۱۰۰٪ حریم خصوصی، اطلاعات شخصی (وزن، قد، پروفایل) فقط در چت خصوصی ثبت و نمایش داده می‌شود.\n"
                    "لطفاً روی دکمه زیر کلیک کنید:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            elif update.callback_query:
                await update.callback_query.answer("لطفاً برای اطلاعات شخصی به چت خصوصی ربات بروید.", show_alert=True)
            return # متوقف کردن اجرای دستور اصلی
            
        return await func(update, context, *args, **kwargs)
    return wrapper


def rate_limited(func):
    """
    دکوراتور امنیتی: جلوگیری از اسپم شدن ربات در گروه‌ها
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return await func(update, context, *args, **kwargs)

        user_id = update.effective_user.id
        current_time = time.time()
        
        # محدودیت ۲ ثانیه‌ای بین هر پیام
        if user_id in _user_last_message_time:
            if current_time - _user_last_message_time[user_id] < 2.0:
                return # نادیده گرفتن پیام برای جلوگیری از بن شدن
                
        _user_last_message_time[user_id] = current_time
        return await func(update, context, *args, **kwargs)
    return wrapper
