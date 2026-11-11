"""دستور اختصاصی کانفیگ با دکمه‌های کپی"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from app.config import get_settings
from app.services.config_service import get_fresh_configs

logger = logging.getLogger(__name__)

async def cmd_getconfig(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not get_settings().is_admin(user.id):
        return await update.message.reply_text("⛔️ این دستور فقط برای صاحب ربات است.")
    
    status = await update.message.reply_text("🔄 در حال جستجو، تست و اعتبارسنجی جدیدترین کانفیگ‌ها... (حدود ۵ تا ۱۰ ثانیه)")
    
    try:
        configs = await get_fresh_configs(limit=10)
        
        # ذخیره برای دکمه‌ها
        context.user_data["saved_configs"] = configs
        
        text_lines = ["✅ **کانفیگ‌های سالم (اولویت با جدیدها و مناسب ایران):**\n"]
        keyboard = []
        
        for i, c in enumerate(configs, 1):
            protocol = c.split("://")[0].upper()
            # یک متن کوتاه برای نمایش
            short = c[:30] + "..." if len(c) > 30 else c
            text_lines.append(f"{i}. [{protocol}] `{short}`")
            keyboard.append([InlineKeyboardButton(f"📋 کپی کانفیگ {i} ({protocol})", callback_data=f"copy_cfg_{i}")])
            
        keyboard.append([InlineKeyboardButton("🔄 دریافت کانفیگ‌های جدید", callback_data="refresh_cfg")])
        
        await status.edit_text(
            "\n".join(text_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Config error: {e}", exc_info=True)
        await status.edit_text("⚠️ خطای غیرمنتظره رخ داد.")

async def handle_config_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    
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
    elif data == "refresh_cfg":
        # حذف پیام قبلی و گرفتن کانفیگ جدید
        await query.message.delete()
        await cmd_getconfig(update, context)
