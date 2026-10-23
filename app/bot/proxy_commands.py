"""دستور پروکسی (بدون متن اضافه، فقط دکمه‌های اتصال)"""

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

    status_msg = await update.message.reply_text("🔄 در حال دریافت جدیدترین پروکسی‌ها...")

    try:
        proxies = await get_best_proxies(limit=30)

        if not proxies:
            return await status_msg.edit_text("❌ فعلاً پروکسی پیدا نشد. کمی بعد دوباره امتحان کنید.")

        keyboard = []
        # ساخت ۳۰ دکمه شیشه‌ای
        for i, p in enumerate(proxies, 1):
            keyboard.append([InlineKeyboardButton(f"🔗 اتصال به پروکسی {i}", url=p["proxy"])])

        keyboard.append([InlineKeyboardButton("🔄 دریافت مجدد", callback_data="proxy_refresh")])
        keyboard.append([InlineKeyboardButton("❌ بستن", callback_data="proxy_close")])

        await status_msg.edit_text(
            "👇 روی هر دکمه بزنید تا مستقیم در تلگرام باز شود:",
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
