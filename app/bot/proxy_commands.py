"""دستور پروکسی (فقط دکمه‌های زنده)"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.config import get_settings
from app.services.proxy_service import get_best_proxies

logger = logging.getLogger(__name__)

async def cmd_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id):
        return await update.message.reply_text("⛔️ فقط برای صاحب ربات.")

    status_msg = await update.message.reply_text("🔄 در حال دریافت و تست پروکسی‌های زنده...")

    try:
        proxies = await get_best_proxies(limit=20)

        if not proxies:
            return await status_msg.edit_text("❌ الان هیچ پروکسی زنده‌ای پیدا نشد. چند دقیقه دیگه دوباره بزن.")

        keyboard = []
        for i, p in enumerate(proxies, 1):
            keyboard.append([InlineKeyboardButton(f"🔗 پروکسی زنده {i}", url=p["proxy"])])

        keyboard.append([InlineKeyboardButton("🔄 تست مجدد", callback_data="proxy_refresh")])
        keyboard.append([InlineKeyboardButton("❌ بستن", callback_data="proxy_close")])

        await status_msg.edit_text(
            "👇 اینا الان زنده هستن، سریع بزن:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await status_msg.edit_text("⚠️ خطا.")

async def handle_proxy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "proxy_refresh":
        await query.message.delete()
        await cmd_proxy(update, context)
    elif query.data == "proxy_close":
        await query.message.delete()
