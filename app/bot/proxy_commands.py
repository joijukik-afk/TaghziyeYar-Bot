"""دستورات مدیریت پروکسی برای ربات (نسخه MTProto)"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.config import get_settings
from app.services.proxy_service import get_best_proxies

logger = logging.getLogger(__name__)

async def cmd_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دریافت جدیدترین پروکسی‌های MTProto"""
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id):
        return await update.message.reply_text("⛔️ این دستور فقط برای صاحب ربات است.")

    status_msg = await update.message.reply_text("🔄 در حال دریافت جدیدترین پروکسی‌های MTProto از منابع معتبر...")

    try:
        best_proxies = await get_best_proxies(limit=30)

        if not best_proxies:
            return await status_msg.edit_text("❌ متأسفانه در حال حاضر هیچ پروکسی سالمی پیدا نشد. لطفاً بعداً تلاش کنید.")

        text_lines = [f"✅ **{len(best_proxies)} پروکسی MTProto جدید پیدا شد:**\n\n"]
        keyboard = []

        for i, p in enumerate(best_proxies, 1):
            proxy_link = p['proxy']
            # نمایش کوتاه شده لینک در متن
            display_link = proxy_link.replace("https://t.me/proxy?", "")
            text_lines.append(f"{i}. `{display_link}`\n")
            
            # دکمه برای اتصال مستقیم
            keyboard.append([InlineKeyboardButton(f"🔗 اتصال به پروکسی {i}", url=proxy_link)])

        keyboard.append([InlineKeyboardButton("🔄 به‌روزرسانی لیست", callback_data="proxy_refresh")])
        keyboard.append([InlineKeyboardButton("❌ بستن", callback_data="proxy_close")])

        final_text = "".join(text_lines)
        # جلوگیری از ارور طولانی بودن متن تلگرام
        if len(final_text) > 4000:
            final_text = "".join(text_lines[:20]) + "\n\n(به دلیل محدودیت طول پیام، بقیه پروکسی‌ها در دکمه‌های زیر موجود هستند)"

        await status_msg.edit_text(
            final_text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception as e:
        logger.error(f"Error in cmd_proxy: {e}", exc_info=True)
        await status_msg.edit_text("⚠️ خطایی در حین دریافت پروکسی‌ها رخ داد.")

async def handle_proxy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت دکمه‌های شیشه‌ای"""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "proxy_refresh":
        await query.message.delete()
        await cmd_proxy(update, context)
    elif data == "proxy_close":
        await query.message.delete()
