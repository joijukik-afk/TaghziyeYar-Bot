"""Register bot commands with Telegram's menu."""

import logging
from telegram import Bot, BotCommand

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    # عمومی
    BotCommand("start", "🚀 شروع کار با ربات"),
    BotCommand("help", "📖 راهنمای کامل"),
    BotCommand("menu", "🏠 منوی اصلی"),

    # ابزارهای هوشمند
    BotCommand("search", "🔍 جستجوی هوشمند"),
    BotCommand("translate", "🌐 ترجمه هوشمند"),
    BotCommand("voice", "🎙️ چت صوتی"),
    BotCommand("tts", "🔊 تبدیل متن به صدا"),
    BotCommand("sticker", "🎨 ساخت استیکر از متن"),
    BotCommand("imagine", "🖼️ تولید عکس با AI"),

    # موسیقی
    BotCommand("koma", "🎧 موسیقی COMA"),
    BotCommand("music", "🎵 دانلود آهنگ"),

    # بازی و سرگرمی
    BotCommand("quiz", "🎮 کوییز زنده"),
    BotCommand("snake", "🐍 بازی مار و پله"),
    BotCommand("leaderboard", "🏆 جدول قهرمانان"),
    BotCommand("mystats", "📊 آمار من"),

    # برنامه غذایی
    BotCommand("plan", "🍽 برنامه غذایی"),
    BotCommand("today", "📅 برنامه امروز"),
    BotCommand("shopping", "🛒 فهرست خرید"),
    BotCommand("food", "🥗 ارزش غذایی"),

    # پروفایل
    BotCommand("setup", "✏️ تکمیل اطلاعات"),
    BotCommand("profile", "👤 پروفایل من"),
    BotCommand("mycard", "🪪 کارت دیجیتال من"),

    # محاسبات
    BotCommand("bmi", "⚖️ محاسبه BMI"),
    BotCommand("calories", "🔥 کالری روزانه"),
    BotCommand("macros", "🧮 درشت‌مغذی‌ها"),
    BotCommand("protein", "🥩 پروتئین"),
    BotCommand("ideal", "🎯 تحلیل کامل بدن"),
    BotCommand("bodyfat", "📊 چربی بدن"),
    BotCommand("bmr", "⚡ متابولیسم"),

    # پیگیری
    BotCommand("weight", "⚖️ ثبت وزن"),
    BotCommand("progress", "📈 پیشرفت"),
    BotCommand("water", "💧 ثبت آب"),

    # محتوای روزانه
    BotCommand("tip", "💡 نکته تغذیه"),
    BotCommand("fact", "🍎 فکت"),
    BotCommand("myth", "❌ باور اشتباه"),

    # مدیریت
    BotCommand("tagall", "📢 تگ کردن اعضا"),
    BotCommand("setgroup", "📌 ثبت گروه"),
    BotCommand("proxy", "🌐 لیست پروکسی"),
    BotCommand("getconfig", "⚙️ کانفیگ V2Ray"),

    # سایر
    BotCommand("about", "ℹ️ درباره ربات"),
    BotCommand("privacy", "🔒 حریم خصوصی"),
    BotCommand("settings", "⚙️ تنظیمات"),
]

async def setup_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands(BOT_COMMANDS)
        logger.info("Bot commands registered: %d commands", len(BOT_COMMANDS))
    except Exception as e:
        logger.warning("Failed to register commands: %s", e)
