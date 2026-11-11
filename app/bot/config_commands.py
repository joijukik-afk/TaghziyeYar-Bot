"""دستور اختصاصی دریافت کانفیگ V2Ray (فقط صاحب ربات)"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.config import get_settings
from app.services.config_service import get_fresh_configs

logger = logging.getLogger(__name__)

async def cmd_getconfig(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دریافت کانفیگ‌های جدید V2Ray (فقط مالک)"""
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id):
        return await update.message.reply_text("⛔️ این دستور فقط برای صاحب ربات است.")
    
    status = await update.message.reply_text("🔄 در حال جمع‌آوری و تست کانفیگ‌های جدید...")
    
    try:
        configs = await get_fresh_configs(limit=10)
        
        if not configs:
            return await status.edit_text("❌ کانفیگ جدیدی پیدا نشد. لطفاً بعداً تلاش کنید.")
        
        # ارسال کانفیگ‌ها به صورت دکمه‌های شیشه‌ای (برای کپی راحت)
        keyboard = []
        for i, c in enumerate(configs, 1):
            # دکمه برای کپی کردن متن کانفیگ
            keyboard.append([InlineKeyboardButton(f"🔗 کانفیگ {i}", callback_data=f"copy_config_{i}")])
        
        # ارسال لیست به عنوان متن (با قابلیت کپی)
        text_lines = [f"✅ **{len(configs)} کانفیگ جدید (مناسب ایران):**\n"]
        for i, c in enumerate(configs, 1):
            # نمایش کوتاه شده برای خوانایی
            short = c[:50] + "..." if len(c) > 50 else c
            text_lines.append(f"{i}. `{short}`")
        
        await status.edit_text(
            "\n".join(text_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    except Exception as e:
        logger.error(f"Config error: {e}", exc_info=True)
        await status.edit_text("⚠️ خطایی رخ داد.")

async def handle_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مدیریت دکمه‌های کپی کانفیگ"""
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("copy_config_"):
        # ارسال یک پیام موقت با متن کامل کانفیگ
        await query.message.reply_text(
            "📋 **کانفیگ شما (برای کپی روی آن ضربه بزنید):**\n\n"
            "`" + context.user_data.get("configs", [""])[int(data.split("_")[-1]) - 1] + "`",
            parse_mode="Markdown"
        )
