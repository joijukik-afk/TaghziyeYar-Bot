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
    BotCommand("imagine", "🎨 تولید عکس با هوش مصنوعی"),
    BotCommand("search", "🔍 جستجوی هوشمند در وب"),
    BotCommand("translate", "🌐 ترجمه هوشمند متن"),
    BotCommand("voice", "🎙️ چت صوتی با هوش مصنوعی"),
    BotCommand("tts", "🔊 تبدیل متن به صدا"),

    # موسیقی
    BotCommand("koma", "🎧 کشف موسیقی COMA"),
    BotCommand("music", "🎵 دانلود آهنگ خاص"),
    BotCommand("koma_random", "🎲 آهنگ تصادفی COMA"),

    # بازی و سرگرمی
    BotCommand("quiz", "🎮 کوییز زنده"),
    BotCommand("snake", "🐍 بازی مار و پله"),
    BotCommand("leaderboard", "🏆 جدول قهرمانان"),
    BotCommand("mystats", "📊 آمار من"),

    # برنامه غذایی
    BotCommand("plan", "🍽 ساخت برنامه غذایی"),
    BotCommand("today", "📅 برنامه امروز"),
    BotCommand("shopping", "🛒 فهرست خرید"),
    BotCommand("food", "🥗 ارزش غذایی غذا"),

    # پروفایل
    BotCommand("setup", "✏️ تکمیل یا ویرایش اطلاعات"),
    BotCommand("profile", "👤 پروفایل من"),
    BotCommand("mycard", "🪪 کارت گرافیکی من"),

    # محاسبات
    BotCommand("bmi", "⚖️ محاسبه BMI"),
    BotCommand("calories", "🔥 نیاز کالری روزانه"),
    BotCommand("macros", "🧮 درشت‌مغذی‌ها"),
    BotCommand("protein", "🥩 نیاز پروتئین"),
    BotCommand("ideal", "🎯 تحلیل کامل بدن"),
    BotCommand("bodyfat", "📊 تخمین چربی بدن"),
    BotCommand("bmr", "⚡ متابولیسم پایه"),

    # پیگیری
    BotCommand("weight", "⚖️ ثبت وزن جدید"),
    BotCommand("progress", "📈 گزارش پیشرفت"),
    BotCommand("water", "💧 ثبت آب"),

    # محتوای روزانه
    BotCommand("tip", "💡 نکته تغذیه‌ای"),
    BotCommand("fact", "🍎 فکت جالب"),
    BotCommand("myth", "❌ باور اشتباه"),

    # مدیریت گروه
    BotCommand("tagall", "📢 تگ کردن اعضا (ادمین)"),
    BotCommand("setgroup", "📌 ثبت گروه برای پست خودکار"),

    # ادمین
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
