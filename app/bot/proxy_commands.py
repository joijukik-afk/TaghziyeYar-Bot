"""دستورات مدیریت پروکسی برای ربات KOMA"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.config import get_settings
from app.services.proxy_service import proxy_pool

logger = logging.getLogger(__name__)

async def cmd_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دریافت لیست برترین پروکسی‌های سالم"""
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id):
        # استفاده از effective_message برای سازگاری با کال بک و کامند
        if update.effective_message:
            return await update.effective_message.reply_text("⛔️ این دستور فقط برای صاحب ربات است.")
        return

    if not update.effective_message:
        return

    status_msg = await update.effective_message.reply_text("🔄 در حال جمع‌آوری و تست پروکسی‌ها از منابع مختلف...\n(این ممکن است ۱۰-۳۰ ثانیه طول بکشد)")

    try:
        best_proxies = await proxy_pool.get_best_proxies(limit=30)
        
        if not best_proxies:
            return await status_msg.edit_text("❌ متأسفانه در حال حاضر هیچ پروکسی سالمی پیدا نشد. لطفاً بعداً تلاش کنید.")

        text_lines = [f"✅ **{len(best_proxies)} پروکسی سالم و سریع پیدا شد:**\n"]
        keyboard = []

        for i, p in enumerate(best_proxies, 1):
            # نمایش پروکسی به همراه سرعت و نرخ موفقیت
            text_lines.append(f"{i}. `{p['proxy']}` (تأخیر: {p['latency']}s | موفقیت: {p['success_rate']}%)")
            # دکمه برای کپی کردن
            keyboard.append([InlineKeyboardButton(f"📋 کپی پروکسی {i}", callback_data=f"proxy_copy_{p['proxy']}")])

        keyboard.append([InlineKeyboardButton("🔄 به‌روزرسانی لیست", callback_data="proxy_refresh")])
        keyboard.append([InlineKeyboardButton("❌ بستن", callback_data="proxy_close")])

        await status_msg.edit_text(
            "\n".join(text_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Error in cmd_proxy: {e}", exc_info=True)
        await status_msg.edit_text("⚠️ خطایی در حین دریافت پروکسی‌ها رخ داد.")

async def handle_proxy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت دکمه‌های شیشه‌ای"""
    query = update.callback_query
    if not query: return
    await query.answer()
    
    data = query.data

    if data == "proxy_refresh":
        # پیام قدیمی رو حذف نمیکنیم، بلکه همون رو ادیت میکنیم که تمیزتر باشه
        await query.message.edit_text("🔄 در حال به‌روزرسانی لیست...")
        # برای رفرش، یک آپدیت مصنوعی میسازیم که message داره
        # یا خیلی ساده‌تر، تابع اصلی رو با همون message صدا می‌زنیم
        class FakeUpdate:
            def __init__(self, query):
                self.effective_user = query.from_user
                self.effective_message = query.message
                self.message = query.message
        await cmd_proxy(FakeUpdate(query), context)
        
    elif data == "proxy_close":
        await query.message.delete()
        
    elif data.startswith("proxy_copy_"):
        proxy_url = data.replace("proxy_copy_", "")
        # به جای ارسال پیام جدید، یک پاپ‌آپ (Alert) نشون میده که میتونی کپی کنی
        await query.answer(f"پروکسی کپی شد:\n{proxy_url}", show_alert=True)
