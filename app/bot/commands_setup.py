"""Register bot commands with Telegram's menu using Scopes for better UX."""

import logging
from telegram import Bot, BotCommand, BotCommandScopeDefault, BotCommandScopeChat, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats
from app.config import get_settings

logger = logging.getLogger(__name__)

# 👈 ۱. دستورات عمومی (هم در گروه و هم در پیوی)
GENERAL_COMMANDS = [
    BotCommand("start", "🚀 شروع کار با ربات"),
    BotCommand("help", "📖 راهنمای کامل"),
    BotCommand("menu", "🏠 منوی اصلی"),
    BotCommand("search", "🔍 جستجوی هوشمند"),
    BotCommand("translate", "🌐 ترجمه هوشمند"),
    BotCommand("voice", "🎙️ چت صوتی"),
    BotCommand("tts", "🔊 تبدیل متن به صدا"),
    BotCommand("imagine", "🖼️ تولید عکس با AI"),
    BotCommand("vision", "👁️ تحلیل عکس"),
    BotCommand("barcode", "📸 اسکن بارکد غذا"),
    BotCommand("koma", "🎧 موسیقی COMA"),
    BotCommand("music", "🎵 دانلود آهنگ"),
    BotCommand("quiz", "🎮 کوییز زنده"),
    BotCommand("snake", "🐍 بازی مار"),
    BotCommand("leaderboard", "🏆 جدول قهرمانان"),
    BotCommand("mystats", "📊 آمار من"),
    BotCommand("plan", "🍽 برنامه غذایی"),
    BotCommand("today", "📅 برنامه امروز"),
    BotCommand("shopping", "🛒 فهرست خرید"),
    BotCommand("food", "🥗 ارزش غذایی"),
    BotCommand("bmi", "⚖️ محاسبه BMI"),
    BotCommand("tip", "💡 نکته تغذیه"),
    BotCommand("fact", "🍎 فکت"),
    BotCommand("myth", "❌ باور اشتباه"),
    BotCommand("about", "ℹ️ درباره ربات"),
    BotCommand("privacy", "🔒 حریم خصوصی"),
]

# 👈 ۲. دستورات چت خصوصی (فقط در پیوی)
PRIVATE_COMMANDS = [
    BotCommand("setup", "✏️ تکمیل اطلاعات"),
    BotCommand("profile", "👤 پروفایل من"),
    BotCommand("mycard", "🪪 کارت دیجیتال من"),
    BotCommand("calories", "🔥 کالری روزانه"),
    BotCommand("macros", "🧮 درشت‌مغذی‌ها"),
    BotCommand("protein", "🥩 پروتئین"),
    BotCommand("ideal", "🎯 تحلیل کامل بدن"),
    BotCommand("bodyfat", "📊 چربی بدن"),
    BotCommand("bmr", "⚡ متابولیسم"),
    BotCommand("weight", "⚖️ ثبت وزن"),
    BotCommand("progress", "📈 پیشرفت"),
    BotCommand("water", "💧 ثبت آب"),
    BotCommand("remind", "⏰ یادآوری"),
    BotCommand("cancel", "❌ لغو عملیات"),
]

# 👈 ۳. دستورات ادمین (فقط برای شما)
ADMIN_COMMANDS = [
    BotCommand("tagall", "📢 تگ کردن اعضا"),
    BotCommand("setgroup", "📌 ثبت گروه"),
    BotCommand("groups", "📋 لیست گروه‌ها"),
    BotCommand("leave", "🚪 خروج از گروه"),
    BotCommand("sendto", "📤 ارسال به گروه"),
    BotCommand("globalnews", "📰 خبر فوری"),
    BotCommand("broadcast_covers", "🎨 کاور گروه‌ها"),
    BotCommand("advertise", "📣 کمپین تبلیغاتی"),
    BotCommand("forcepost", "⚡ پست فوری"),
    BotCommand("addadmin", "👑 افزودن ادمین"),
    BotCommand("removeadmin", "🚫 حذف ادمین"),
    BotCommand("admins", "📋 لیست ادمین‌ها"),
    BotCommand("ban", "🔨 مسدود کردن"),
    BotCommand("unban", "🔓 رفع مسدودی"),
    BotCommand("proxy", "🌐 لیست پروکسی"),
    BotCommand("getconfig", "⚙️ کانفیگ V2Ray"),
]

async def setup_commands(bot: Bot) -> None:
    """تنظیم منوهای ربات برای سطوح مختلف دسترسی"""
    try:
        settings = get_settings()
        
        await bot.set_my_commands(GENERAL_COMMANDS, scope=BotCommandScopeDefault())
        await bot.set_my_commands(GENERAL_COMMANDS + PRIVATE_COMMANDS, scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(GENERAL_COMMANDS, scope=BotCommandScopeAllGroupChats())
        
        # منوی اختصاصی برای ادمین‌ها
        for admin_id in settings.admin_ids:
            try:
                await bot.set_my_commands(
                    GENERAL_COMMANDS + PRIVATE_COMMANDS + ADMIN_COMMANDS,
                    scope=BotCommandScopeChat(chat_id=admin_id)
                )
            except Exception as e:
                logger.warning(f"Could not set admin commands for {admin_id}: {e}")
                
        logger.info("Bot commands registered successfully with Scopes.")
        
    except Exception as e:
        logger.error("Failed to register commands: %s", e, exc_info=True)
