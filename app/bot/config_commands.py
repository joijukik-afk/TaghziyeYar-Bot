"""دستور اختصاصی کانفیگ با دکمه‌های کپی و رفرش فیکس‌شده"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.config import get_settings
from app.services.config_service import get_fresh_configs

logger = logging.getLogger(__name__)

async def _build_config_message(update: Update, context: ContextTypes.DEFAULT_TYPE, is_edit: bool = False):
    """تابع کمکی برای ساخت لیست کانفیگ‌ها و دکمه‌ها"""
    configs = await get_fresh_configs(limit=15)
    context.user_data["saved_configs"] = configs
    
    text_lines = ["🚀 **کانفیگ‌های حرفه‌ای (تست‌شده و مناسب ایران):**\n\n"]
    keyboard = []
    
    for i, c in enumerate(configs, 1):
        protocol = c.split("://")[0].upper()
        # کوتاه کردن برای نمایش
        short = c[:35] + "..." if len(c) > 35 else c
        text_lines.append(f"{i}. [{protocol}] `{short}`\n")
        
        # دکمه کپی برای هر کانفیگ
        keyboard.append([InlineKeyboardButton(f"📋 کپی کانفیگ {i} ({protocol})", callback_data=f"copy_cfg_{i}")])
        
    # دکمه رفرش
    keyboard.append([InlineKeyboardButton("🔄 دریافت کانفیگ‌های جدیدتر", callback_data="refresh_cfg")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    final_text = "".join(text_lines)
    
    if is_edit and update.callback_query:
        await update.callback_query.message.edit_text(
            final_text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
    else:
        await update.message.reply_text(
            final_text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

async def cmd_getconfig(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id):
        return await update.message.reply_text("⛔️ این دستور فقط برای صاحب ربات است.")
    
    status = await update.message.reply_text("🔄 در حال جستجو، تست و اعتبارسنجی جدیدترین کانفیگ‌ها... (حدود ۵ تا ۱۰ ثانیه)")
    
    try:
        await _build_config_message(update, context)
        await status.delete()
    except Exception as e:
        logger.error(f"Config error: {e}", exc_info=True)
        await status.edit_text("⚠️ خطای غیرمنتظره رخ داد.")

async def handle_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    
    # دکمه کپی
    if data.startswith("copy_cfg_"):
        idx = int(data.split("_")[-1]) - 1
        configs = context.user_data.get("saved_configs", [])
        
        if idx < len(configs):
            # ارسال به صورت HTML code block برای کپی راحت با یک ضربه
            await query.message.reply_text(
                f"📋 **کانفیگ {idx+1} (روی متن زیر ضربه بزنید تا کپی شود):**\n\n"
                f"<code>{configs[idx]}</code>",
                parse_mode="HTML"
            )
            
    # دکمه رفرش
    elif data == "refresh_cfg":
        await query.message.edit_text("🔄 در حال دریافت کانفیگ‌های جدید...")
        try:
            await _build_config_message(update, context, is_edit=True)
        except Exception as e:
            logger.error(f"Refresh error: {e}", exc_info=True)
            await query.message.edit_text("⚠️ خطا در دریافت مجدد کانفیگ‌ها.")
