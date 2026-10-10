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

from app.bot import messages as msg
from app.bot import profile_commands as pcmd
from app.bot import setup_wizard as wizard
from app.config import get_settings
from app.database import repository as repo
from app.database.session import create_all, dispose_engine, init_engine
from app.utils.message_formatter import with_signature


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=get_settings().log_level,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Health-check HTTP server (required by Render)
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
        pass  # silence default logging


def _start_health_server() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
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
        [InlineKeyboardButton("🥗 برنامه غذایی من", callback_data="menu_plan")],
        [
            InlineKeyboardButton("⚖️ ثبت وزن", callback_data="menu_weight"),
            InlineKeyboardButton("🔥 محاسبه کالری", callback_data="menu_calories"),
        ],
        [
            InlineKeyboardButton("📊 گزارش پیشرفت", callback_data="menu_progress"),
            InlineKeyboardButton("🛒 فهرست خرید", callback_data="menu_shopping"),
        ],
        [
            InlineKeyboardButton("👤 پروفایل من", callback_data="menu_profile"),
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
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    if chat and chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        await repo.get_or_create_group(chat_id=chat.id, title=chat.title)


# ---------------------------------------------------------------------------
#  Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    if update.message is None:
        return
    await update.message.reply_text(
        with_signature(msg.WELCOME),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    if update.message is None:
        return
    await update.message.reply_text(
        with_signature(msg.HELP),
        parse_mode="Markdown",
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await ensure_user_and_group(update)
    if update.message is None:
        return
    await update.message.reply_text(
        with_signature(msg.MENU_TEXT),
        parse_mode="Markdown",
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
            "lose": "کاهش وزن",
            "gain": "افزایش وزن",
            "muscle": "عضله‌سازی",
            "maintain": "حفظ وزن",
            "quality": "بهبود کیفیت تغذیه",
            "sport": "هدف ورزشی",
        }.get(profile.goal, profile.goal)
        lines.append(f"• هدف: {goal_fa}")
    if profile.activity_level:
        act_fa = {
            "sedentary": "کم‌تحرک",
            "light": "سبک",
            "moderate": "متوسط",
            "high": "زیاد",
        }.get(profile.activity_level, profile.activity_level)
        lines.append(f"• فعالیت: {act_fa}")

    lines.append("\n✏️ برای ویرایش اطلاعات، /setup رو بزن.")

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
#  Generic text router
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

    reply = (
        f"پیام تو رو گرفتم: {text}\n\n"
        "برای استفاده از امکانات من:\n"
        "• /setup — ساخت پروفایل\n"
        "• /bmi — محاسبه BMI\n"
        "• /calories — کالری روزانه\n"
        "• /help — راهنمای کامل"
    )
    await update.message.reply_text(with_signature(reply))


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    data = query.data or ""

    if data == "menu_help":
        await query.edit_message_text(
            with_signature(msg.HELP), parse_mode="Markdown"
        )
        return

    if data == "menu_profile":
        await query.edit_message_text(
            with_signature("👤 برای دیدن پروفایل، دستور /profile رو بزن."),
            parse_mode="Markdown",
        )
        return

    mapping = {
        "menu_plan": "🥗 برنامه غذایی هنوز فعال نشده. تو فاز بعدی میاد.",
        "menu_weight": "⚖️ برای ثبت وزن، دستور /weight رو بزن.",
        "menu_calories": "🔥 برای محاسبه کالری، دستور /calories رو بزن.",
        "menu_progress": "📊 برای گزارش پیشرفت، دستور /progress رو بزن.",
        "menu_shopping": "🛒 فهرست خرید هنوز فعال نشده.",
    }
    text = mapping.get(data, msg.UNKNOWN_COMMAND)
    await query.edit_message_text(with_signature(text), parse_mode="Markdown")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Exception while handling update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message is not None:
        try:
            await update.effective_message.reply_text(
                with_signature(msg.ERROR_GENERIC)
            )
        except Exception:
            pass


async def post_init(app: Application) -> None:
    init_engine()
    await create_all()
    me = await app.bot.get_me()
    logger.info("Bot started as @%s (id=%s)", me.username, me.id)


async def post_shutdown(app: Application) -> None:
    await dispose_engine()
    logger.info("Bot stopped.")


def build_application() -> Application:
    settings = get_settings()
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("privacy", cmd_privacy))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("profile", cmd_profile))

    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CommandHandler("cancel", cmd_cancel))

    app.add_handler(CommandHandler("bmi", cmd_bmi))
    app.add_handler(CommandHandler("calories", cmd_calories))
    app.add_handler(CommandHandler("weight", cmd_weight))
    app.add_handler(CommandHandler("progress", cmd_progress))

    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(on_error)

    return app


def main() -> None:
    _start_health_server()
    app = build_application()
    logger.info("Starting bot...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
