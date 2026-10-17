import time
import logging
from functools import wraps
from telegram import Update, ChatMember, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.config import settings

logger = logging.getLogger(__name__)

# دیکشنری برای ذخیره زمان آخرین پیام کاربر (برای جلوگیری از اسپم)
_user_last_message_time = {}

def restricted_to_private(func):
    """
    این دکوراتور باعث می‌شود دستوراتی که حاوی اطلاعات شخصی هستند 
    (مثل ثبت وزن و قد) فقط در چت خصوصی کار کنند و در گروه پیام امن بفرستند.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_chat.type != "private":
            # ساخت لینک عمیق برای هدایت به چت خصوصی
            bot_username = context.bot.username
            deep_link = f"https://t.me/{bot_username}?start=private_setup"
            
            keyboard = [[InlineKeyboardButton("🔒 ورود به چت خصوصی", url=deep_link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "🛡️ برای حفظ ۱۰۰٪ حریم خصوصی، اطلاعات شخصی (وزن، قد، سن) فقط در چت خصوصی ثبت می‌شود.\n"
                "لطفاً روی دکمه زیر کلیک کنید:",
                reply_markup=reply_markup
            )
            return # اجرای دستور اصلی متوقف می‌شود
            
        return await func(update, context, *args, **kwargs)
    return wrapper

def rate_limited(func):
    """
    این دکوراتور از اسپم شدن ربات در گروه‌ها و چت خصوصی جلوگیری می‌کند.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not update.effective_user:
            return await func(update, context, *args, **kwargs)

        user_id = update.effective_user.id
        current_time = time.time()
        
        # بررسی زمان آخرین پیام
        if user_id in _user_last_message_time:
            time_passed = current_time - _user_last_message_time[user_id]
            if time_passed < settings.rate_limit_seconds:
                # اگر کاربر اسپم کرده، ربات جواب نمی‌دهد (برای جلوگیری از بن شدن بات توسط تلگرام)
                logger.warning(f"Rate limit hit by user {user_id}")
                return
                
        _user_last_message_time[user_id] = current_time
        return await func(update, context, *args, **kwargs)
    return wrapper

def group_admin_only(func):
    """
    بررسی می‌کند که آیا کاربری که دستور را در گروه زده است، ادمین گروه هست یا نه.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_chat.type == "private":
            return await func(update, context, *args, **kwargs) # در پی وی نیازی به چک کردن نیست
            
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                await update.message.reply_text("⛔️ این دستور فقط برای ادمین‌های این گروه مجاز است.")
                return
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            return
            
        return await func(update, context, *args, **kwargs)
    return wrapper
