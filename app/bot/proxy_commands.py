"""دستورات مدیریت پروکسی (فقط دکمه‌ها)"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.config import get_settings
from app.services.proxy_service import get_best_proxies

logger = logging.getLogger(__name__)

async def cmd_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id):
        return await update.message.reply_text("⛔️ این دستور فقط برای صاحب ربات است.")

    status_msg = await update.message.reply_text("🔄 در حال دریافت پروکسی‌های جدید...")

    try:
        best_proxies = await get_best_proxies(limit=30)

        if not best_proxies:
            return await status_msg.edit_text("❌ پروکسی سالمی پیدا نشد. لطفاً بعداً تلاش کنید.")

        keyboard = []
        for i, p in enumerate(best_proxies, 1):
            # دکمه برای اتصال مستقیم به پروکسی
            keyboard.append([InlineKeyboardButton(f"🔗 پروکسی {i}", url=p['proxy'])])

        keyboard.append([InlineKeyboardButton("🔄 به‌روزرسانی لیست", callback_data="proxy_refresh")])
        keyboard.append([InlineKeyboardButton("❌ بستن", callback_data="proxy_close")])

        await status_msg.edit_text(
            "🔗 **لیست پروکسی‌های MTProto (روی دکمه بزنید):**",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Error in cmd_proxy: {e}", exc_info=True)
        await status_msg.edit_text("⚠️ خطایی رخ داد.")

async def handle_proxy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "proxy_refresh":
        await query.message.delete()
        await cmd_proxy(update, context)
    elif data == "proxy_close":
        await query.message.delete()
