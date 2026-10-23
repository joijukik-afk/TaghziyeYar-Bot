"""دستورات مدیریت پروکسی"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.config import get_settings
from app.services.proxy_service import proxy_pool

logger = logging.getLogger(__name__)

async def cmd_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id):
        if update.effective_message:
            return await update.effective_message.reply_text("⛔️ این دستور فقط برای صاحب ربات است.")
        return

    if not update.effective_message:
        return

    # ارسال پیام اولیه
    status_msg = await update.effective_message.reply_text("🔄 در حال تست پروکسی‌ها... (حداکثر ۲۰ ثانیه)")

    try:
        # دریافت لیست (دارای تایم‌اوت داخلی)
        best_proxies = await proxy_pool.get_best_proxies(limit=30)
        
        if not best_proxies:
            return await status_msg.edit_text("❌ متأسفانه هیچ پروکسی سالمی پیدا نشد (تایم‌اوت یا مسدود). بعداً تلاش کنید.")

        text_lines = [f"✅ **{len(best_proxies)} پروکسی سالم پیدا شد:**\n"]
        keyboard = []

        for i, p in enumerate(best_proxies, 1):
            text_lines.append(f"{i}. `{p['proxy']}` ({p['latency']}s)")
            keyboard.append([InlineKeyboardButton(f"📋 کپی {i}", callback_data=f"proxy_copy_{p['proxy']}")])

        keyboard.append([InlineKeyboardButton("🔄 به‌روزرسانی", callback_data="proxy_refresh")])
        keyboard.append([InlineKeyboardButton("❌ بستن", callback_data="proxy_close")])

        await status_msg.edit_text(
            "\n".join(text_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Error in cmd_proxy: {e}", exc_info=True)
        await status_msg.edit_text("⚠️ خطایی رخ داد. لطفاً دوباره تلاش کنید.")

async def handle_proxy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query: return
    await query.answer()
    
    data = query.data

    if data == "proxy_refresh":
        await query.message.edit_text("🔄 در حال به‌روزرسانی...")
        # یک آپدیت جعلی برای فراخوانی مجدد تابع اصلی می‌سازیم
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
        await query.answer(f"کپی شد:\n{proxy_url}", show_alert=True)
