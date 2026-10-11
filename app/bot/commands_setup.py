"""Register bot commands with Telegram's menu."""

import logging

from telegram import Bot, BotCommand

logger = logging.getLogger(__name__)


BOT_COMMANDS = [
    BotCommand("start", "🚀 شروع کار با ربات"),
    BotCommand("help", "📖 راهنمای کامل"),
    BotCommand("menu", "🏠 منوی اصلی"),

    BotCommand("plan", "🍽 ساخت برنامه غذایی"),
    BotCommand("today", "📅 برنامه امروز"),
    BotCommand("shopping", "🛒 فهرست خرید"),
    BotCommand("food", "🥗 ارزش غذایی غذا"),

    BotCommand("setup", "✏️ تکمیل یا ویرایش اطلاعات"),
    BotCommand("profile", "👤 پروفایل من"),

    BotCommand("bmi", "⚖️ محاسبه BMI"),
    BotCommand("calories", "🔥 نیاز کالری روزانه"),
    BotCommand("macros", "🧮 درشت‌مغذی‌ها"),
    BotCommand("protein", "🥩 نیاز پروتئین"),
    BotCommand("ideal", "🎯 تحلیل کامل بدن"),
    BotCommand("bodyfat", "📊 تخمین چربی بدن"),
    BotCommand("bmr", "⚡ متابولیسم پایه"),

    BotCommand("weight", "⚖️ ثبت وزن جدید"),
    BotCommand("progress", "📈 گزارش پیشرفت"),
    BotCommand("water", "💧 ثبت آب"),

    BotCommand("tip", "💡 نکته تغذیه‌ای"),
    BotCommand("fact", "🍎 فکت جالب"),
    BotCommand("myth", "❌ باور اشتباه"),

    BotCommand("about", "ℹ️ درباره بات"),
    BotCommand("privacy", "🔒 حریم خصوصی"),
    BotCommand("settings", "⚙️ تنظیمات"),
]


async def setup_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands(BOT_COMMANDS)
        logger.info("Bot commands registered: %d commands", len(BOT_COMMANDS))
    except Exception as e:
        logger.warning("Failed to register commands: %s", e)
