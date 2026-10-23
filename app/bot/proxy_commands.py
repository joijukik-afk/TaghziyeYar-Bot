"""دستورات مربوط به مدیریت پروکسی (فقط برای صاحب ربات)"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.config import get_settings
from app.services.proxy_service import get_fast_proxies

logger = logging.getLogger(__name__)

async def cmd_proxies(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دریافت لیست پروکسی‌های سالم و سریع"""
    user = update.effective_user
    # 👇 بررسی اینکه فقط صاحب ربات به این دستور دسترسی داشته باشد
    if not user or not get_settings().is_admin(user.id):
        return await update.message.reply_text("⛔️ این دستور فقط برای صاحب ربات است.")

    status_msg = await update.message.reply_text("🔄 در حال جمع‌آوری و تست پروکسی‌ها از منابع گیت‌هاب... (این ممکن است کمی طول بکشد)")

    try:
        # دریافت لیست پروکسی‌ها
        proxies = await get_fast_proxies()

        if not proxies:
            return await status_msg.edit_text("❌ متأسفانه هیچ پروکسی سالمی در حال حاضر پیدا نشد. لطفاً بعداً تلاش کنید.")

        # ساخت متن خروجی
        text_lines = [f"✅ **{len(proxies)} پروکسی سالم و سریع پیدا شد:**\n"]
        keyboard = []

        for i, p in enumerate(proxies, 1):
            # نمایش پروکسی به همراه سرعت آن
            text_lines.append(f"{i}. `{p['proxy']}` (سرعت: {p['latency']}s)")
            # ساخت دکمه برای کپی کردن راحت‌تر
            keyboard.append([InlineKeyboardButton(f"📋 کپی پروکسی {i}", callback_data=f"proxy_copy_{p['proxy']}")])

        # اضافه کردن دکمه‌های ناوبری
        keyboard.append([InlineKeyboardButton("🔄 به‌روزرسانی لیست", callback_data="proxy_refresh")])
        keyboard.append([InlineKeyboardButton("❌ بستن", callback_data="proxy_close")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        final_text = "\n".join(text_lines)

        await status_msg.edit_text(final_text, parse_mode="Markdown", reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"Error in cmd_proxies: {e}", exc_info=True)
        await status_msg.edit_text("⚠️ خطایی در حین دریافت پروکسی‌ها رخ داد.")

async def handle_proxy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت دکمه‌های شیشه‌ای پروکسی"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "proxy_refresh":
        # دوباره اجرای دستور اصلی
        await query.message.delete()
        await cmd_proxies(update, context)
    
    elif data == "proxy_close":
        await query.message.delete()
    
    elif data.startswith("proxy_copy_"):
        # ارسال یک پیام موقت برای کپی کردن
        proxy_url = data.replace("proxy_copy_", "")
        await query.message.reply_text(f"`{proxy_url}`", parse_mode="Markdown")
