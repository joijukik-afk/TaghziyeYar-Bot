"""Bot entry point. Wires together all handlers and starts polling."""

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.bot import extra_commands as ecmd
from app.bot import group_quiz as gquiz
from app.bot import meal_commands as mcmd
from app.bot import messages as msg
from app.bot import profile_commands as pcmd
from app.bot import setup_wizard as wizard
from app.bot.content import get_fact, get_myth, get_tip
from app.config import get_settings
from app.database import repository as repo
from app.database.session import create_all, dispose_engine, init_engine
from app.services.ai_service import get_ai_service
from app.utils.message_formatter import with_signature

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=get_settings().log_level,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Health server
# ---------------------------------------------------------------------------

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"TaghziyeYar bot is running")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def _start_health_server() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Health server listening on port %s", port)

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def is_group(update: Update) -> bool:
    if update.effective_chat is None:
        return False
    return update.effective_chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)

def is_for_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not is_group(update):
        return True
    bot_username = context.bot.username or ""
    if update.message is None:
        return False
    text = update.message.text or ""
    if f"@{bot_username}" in text:
        return True
    replied = update.message.reply_to_message
    if replied and replied.from_user and replied.from_user.id == context.bot.id:
        return True
    return False

def clean_mention(text: str, bot_username: str) -> str:
    return text.replace(f"@{bot_username}", "").strip()

def main_menu_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("🎮 کوییز زنده", callback_data="menu_quiz"),
            InlineKeyboardButton("🏆 جدول قهرمانان", callback_data="menu_lb"),
        ],
        [
            InlineKeyboardButton("🍽 برنامه غذا", callback_data="menu_plan"),
            InlineKeyboardButton("📅 برنامه امروز", callback_data="menu_today"),
        ],
        [
            InlineKeyboardButton("🛒 فهرست خرید", callback_data="menu_shopping"),
            InlineKeyboardButton("🥗 ارزش غذایی", callback_data="menu_food"),
        ],
        [
            InlineKeyboardButton("💡 نکته روز", callback_data="menu_tip"),
            InlineKeyboardButton("🍎 فکت", callback_data="menu_fact"),
        ],
        [
            InlineKeyboardButton("❌ باور اشتباه", callback_data="menu_myth"),
            InlineKeyboardButton("🎯 تحلیل کامل", callback_data="menu_ideal"),
        ],
        [
            InlineKeyboardButton("⚖️ ثبت وزن", callback_data="menu_weight"),
            InlineKeyboardButton("🔥 کالری", callback_data="menu_calories"),
        ],
        [
            InlineKeyboardButton("🥩 پروتئین", callback_data="menu_protein"),
            InlineKeyboardButton("🧮 درشت‌مغذی", callback_data="menu_macros"),
        ],
        [
            InlineKeyboardButton("📊 پیشرفت", callback_data="menu_progress"),
            InlineKeyboardButton("👤 پروفایل", callback_data="menu_profile"),
        ],
        [
            InlineKeyboardButton("💬 سوال از AI", callback_data="menu_ai"),
            InlineKeyboardButton("📖 راهنما", callback_data="menu_help"),
        ],
    ]
    return InlineKeyboardMarkup(kb)

async def ensure_user_and_group(update: Update) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if user is None:
        return
    await repo.get_or_create_user(
        telegram_id=user.id, username=user.username,
        first_name=user.first_name, last_name=user.last_name,
    )
    if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await repo.get_or_create_group(chat_id=chat.id, title=chat.title)

# ---------------------------------------------------------------------------
#  Base commands
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    if update.message is None:
        return
    await update.message.reply_text(
        with_signature(msg.WELCOME), parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    if update.message is None:
        return
    await update.message.reply_text(with_signature(msg.HELP), parse_mode="Markdown")

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    if update.message is None:
        return
    await update.message.reply_text(
        with_signature(msg.MENU_TEXT), parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )

async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(with_signature(msg.ABOUT), parse_mode="Markdown")

async def cmd_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(with_signature(msg.PRIVACY), parse_mode="Markdown")

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(
        with_signature(msg.SETTINGS_TEXT), parse_mode="Markdown"
    )

async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    user = update.effective_user
    if user is None or update.message is None:
        return
    db_user = await repo.get_user_by_telegram_id(user.id)
    if db_user is None:
        return
    profile = await repo.get_profile(db_user.id)
    if profile is None or not profile.setup_complete:
        await update.message.reply_text(
            with_signature(msg.NOT_SETUP_YET), parse_mode="Markdown"
        )
        return
    lines = ["👤 **پروفایل من**\n"]
    if profile.age:
        lines.append(f"• سن: {profile.age} سال")
    if profile.gender:
        lines.append("• جنسیت: " + ("مرد" if profile.gender == "male" else "زن"))
    if profile.height_cm:
        lines.append(f"• قد: {profile.height_cm:.0f} سانتی‌متر")
    if profile.weight_kg:
        lines.append(f"• وزن: {profile.weight_kg:.1f} کیلوگرم")
    if profile.target_weight_kg:
        lines.append(f"• وزن هدف: {profile.target_weight_kg:.1f} کیلوگرم")
    if profile.goal:
        goal_fa = {
            "lose": "کاهش وزن", "gain": "افزایش وزن",
            "muscle": "عضله‌سازی", "maintain": "حفظ وزن",
            "quality": "بهبود کیفیت تغذیه", "sport": "هدف ورزشی",
        }.get(profile.goal, profile.goal)
        lines.append(f"• هدف: {goal_fa}")
    if profile.activity_level:
        act_fa = {
            "sedentary": "کم‌تحرک", "light": "سبک",
            "moderate": "متوسط", "high": "زیاد",
        }.get(profile.activity_level, profile.activity_level)
        lines.append(f"• فعالیت: {act_fa}")
    lines.append("\n✏️ برای ویرایش، /setup رو بزن.")
    await update.message.reply_text(
        with_signature("\n".join(lines)), parse_mode="Markdown"
    )

async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await wizard.start_setup(update, context)

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    context.user_data["awaiting_weight"] = False
    await wizard.cancel_setup(update, context)

# ---------------------------------------------------------------------------
#  Calculation commands
# ---------------------------------------------------------------------------

async def cmd_bmi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await pcmd.cmd_bmi(update, context)

async def cmd_calories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await pcmd.cmd_calories(update, context)

async def cmd_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await pcmd.cmd_weight(update, context)

async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await pcmd.cmd_progress(update, context)

# ---------------------------------------------------------------------------
#  Extra commands
# ---------------------------------------------------------------------------

async def cmd_tip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await ecmd.cmd_tip(update, context)

async def cmd_fact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await ecmd.cmd_fact(update, context)

async def cmd_myth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await ecmd.cmd_myth(update, context)

async def cmd_water(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await ecmd.cmd_water(update, context)

async def cmd_macros(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await ecmd.cmd_macros(update, context)

async def cmd_protein(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await ecmd.cmd_protein(update, context)

async def cmd_ideal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await ecmd.cmd_ideal(update, context)

async def cmd_bodyfat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await ecmd.cmd_bodyfat(update, context)

async def cmd_bmr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await ecmd.cmd_bmr(update, context)

# ---------------------------------------------------------------------------
#  Meal commands
# ---------------------------------------------------------------------------

async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await mcmd.cmd_plan(update, context)

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await mcmd.cmd_today(update, context)

async def cmd_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await mcmd.cmd_shopping(update, context)

async def cmd_food(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    await mcmd.cmd_food(update, context)

# ---------------------------------------------------------------------------
#  Text -> AI
# ---------------------------------------------------------------------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.message.text is None:
        return
    await ensure_user_and_group(update)
    if not is_for_me(update, context):
        return
    bot_username = context.bot.username or ""
    text = clean_mention(update.message.text, bot_username)
    if not text:
        return
    if await wizard.handle_setup_input(update, context):
        return
    if await pcmd.handle_weight_input(update, context):
        return

    user = update.effective_user
    profile_summary = ""
    if user:
        db_user = await repo.get_user_by_telegram_id(user.id)
        if db_user:
            profile = await repo.get_profile(db_user.id)
            if profile and profile.setup_complete:
                parts = []
                if profile.age:
                    parts.append(f"سن: {profile.age}")
                if profile.height_cm:
                    parts.append(f"قد: {profile.height_cm:.0f}")
                if profile.weight_kg:
                    parts.append(f"وزن: {profile.weight_kg:.1f}")
                if profile.goal:
                    parts.append(f"هدف: {profile.goal}")
                profile_summary = "، ".join(parts)

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )
    except Exception:
        pass

    ai = get_ai_service()
    reply, _ = await ai.ask(
        user_message=text,
        user_name=(user.first_name or "") if user else "",
        user_profile_summary=profile_summary,
        user_id=user.id if user else 0,
    )
    if not reply:
        reply = "متأسفانه پاسخی دریافت نشد."
    await update.message.reply_text(with_signature(reply))

# ---------------------------------------------------------------------------
#  Callbacks
# ---------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""

    # دکمه سوال بعدی
    if data == "gq_next":
        # پاک کردن بازی قبلی
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id and chat_id in gquiz._active_games:
            gquiz._active_games.pop(chat_id, None)

        # شروع بازی جدید
        await gquiz.cmd_quiz(update, context)
        return

    if data == "menu_quiz":
        await query.edit_message_text(
            with_signature(
                "🎮 **کوییز زنده**\n\n"
                "برای شروع، دستور /quiz رو بزن.\n\n"
                "💡 همه می‌تونن شرکت کنن — سریع‌تر = امتیاز بیشتر!"
            ),
            parse_mode="Markdown",
        )
        return

    if data == "menu_lb":
        await query.edit_message_text(
            with_signature("🏆 برای جدول قهرمانان: /leaderboard"),
            parse_mode="Markdown",
        )
        return

    if data == "menu_help":
        await query.edit_message_text(with_signature(msg.HELP), parse_mode="Markdown")
        return

    if data == "menu_tip":
        await query.edit_message_text(
            with_signature(f"💡 **نکته**\n\n{get_tip()}"), parse_mode="Markdown"
        )
        return

    if data == "menu_fact":
        await query.edit_message_text(
            with_signature(f"🍎 **فکت**\n\n{get_fact()}"), parse_mode="Markdown"
        )
        return

    if data == "menu_myth":
        myth, truth = get_myth()
        await query.edit_message_text(
            with_signature(f"❌ **باور اشتباه**\n\n{myth}\n\n✅ **واقعیت**\n{truth}"),
            parse_mode="Markdown",
        )
        return

    hints = {
        "menu_plan": "🍽 برای ساخت برنامه: /plan",
        "menu_today": "📅 برای برنامه امروز: /today",
        "menu_shopping": "🛒 برای فهرست خرید: /shopping",
        "menu_food": "🥗 مثال: `/food تخم مرغ`",
        "menu_ideal": "🎯 برای تحلیل کامل: /ideal",
        "menu_weight": "⚖️ برای ثبت وزن: /weight",
        "menu_calories": "🔥 برای کالری: /calories",
        "menu_protein": "🥩 برای پروتئین: /protein",
        "menu_macros": "🧮 برای درشت‌مغذی: /macros",
        "menu_progress": "📊 برای گزارش: /progress",
        "menu_profile": "👤 برای پروفایل: /profile",
        "menu_ai": "💬 هر پیام آزاد بفرست (بدون /) → AI جواب می‌ده.",
    }
    text = hints.get(data, msg.UNKNOWN_COMMAND)
    await query.edit_message_text(with_signature(text), parse_mode="Markdown")

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Exception", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(
                with_signature(msg.ERROR_GENERIC)
            )
        except Exception:
            pass

# ---------------------------------------------------------------------------
#  Lifecycle
# ---------------------------------------------------------------------------

async def post_init(application: Application) -> None:
    init_engine()
    import app.database.quiz_models  # noqa: F401
    await create_all()
    me = await application.bot.get_me()
    logger.info("Bot started as @%s (id=%s)", me.username, me.id)
    try:
        from app.bot.commands_setup import setup_commands
        await setup_commands(application.bot)
    except Exception as e:
        logger.warning("Setup commands error: %s", e)

async def post_shutdown(application: Application) -> None:
    await dispose_engine()
    logger.info("Bot stopped.")

def build_application() -> Application:
    settings = get_settings()
    application = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Base
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("menu", cmd_menu))
    application.add_handler(CommandHandler("about", cmd_about))
    application.add_handler(CommandHandler("privacy", cmd_privacy))
    application.add_handler(CommandHandler("settings", cmd_settings))
    application.add_handler(CommandHandler("profile", cmd_profile))
    application.add_handler(CommandHandler("setup", cmd_setup))
    application.add_handler(CommandHandler("cancel", cmd_cancel))

    # Calculations
    application.add_handler(CommandHandler("bmi", cmd_bmi))
    application.add_handler(CommandHandler("calories", cmd_calories))
    application.add_handler(CommandHandler("weight", cmd_weight))
    application.add_handler(CommandHandler("progress", cmd_progress))
    application.add_handler(CommandHandler("macros", cmd_macros))
    application.add_handler(CommandHandler("protein", cmd_protein))
    application.add_handler(CommandHandler("ideal", cmd_ideal))
    application.add_handler(CommandHandler("bodyfat", cmd_bodyfat))
    application.add_handler(CommandHandler("bmr", cmd_bmr))

    # Content
    application.add_handler(CommandHandler("tip", cmd_tip))
    application.add_handler(CommandHandler("fact", cmd_fact))
    application.add_handler(CommandHandler("myth", cmd_myth))
    application.add_handler(CommandHandler("water", cmd_water))

    # Meal
    application.add_handler(CommandHandler("plan", cmd_plan))
    application.add_handler(CommandHandler("today", cmd_today))
    application.add_handler(CommandHandler("shopping", cmd_shopping))
    application.add_handler(CommandHandler("food", cmd_food))

    # Live group quiz
    application.add_handler(CommandHandler("quiz", gquiz.cmd_quiz))
    application.add_handler(CommandHandler("leaderboard", gquiz.cmd_leaderboard))
    application.add_handler(CommandHandler("mystats", gquiz.cmd_mystats))
    application.add_handler(CallbackQueryHandler(
        gquiz.handle_group_quiz_answer,
        pattern=r"^gq_(?!next)",  # الگو برای دکمه‌های پاسخ، به جز "next"
    ))

    # Text + callbacks
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_error_handler(on_error)

    return application

def main() -> None:
    _start_health_server()
    application = build_application()
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
