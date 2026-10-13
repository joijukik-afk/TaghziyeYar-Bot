"""ثبت خودکار گروه‌ها + ارسال به همه گروه‌ها."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.config import get_settings
from app.database import repository as repo

logger = logging.getLogger(__name__)


# ============================================================
#  ثبت خودکار
# ============================================================

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """وقتی بات به گروه اضافه شد، chat_id رو ذخیره کن."""
    result = update.my_chat_member
    if result is None:
        return

    chat = result.chat
    if chat.type not in ("group", "supergroup"):
        return

    old_status = result.old_chat_member.status if result.old_chat_member else "left"
    new_status = result.new_chat_member.status

    # فقط وقتی تازه اضافه شده (نه اینکه قبلاً هم بود)
    if old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        await repo.get_or_create_group(chat_id=chat.id, title=chat.title)
        logger.info("✅ بات به گروه اضافه شد: %s (%s)", chat.title, chat.id)

        # پیام خوشامد تو گروه
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    "🥗 سلام! من «تغذیه‌یار» هستم.\n\n"
                    "📌 این گروه ثبت شد و از این به بعد\n"
                    "هر ۸ ساعت یه پست تغذیه‌ای اینجا می‌فرستم.\n\n"
                    "برای شروع: /help"
                ),
            )
        except Exception as e:
            logger.warning("ارسال پیام خوشامد خطا داد: %s", e)


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """از هر پیام تو گروه، chat_id رو ذخیره کن."""
    chat = update.effective_chat
    if chat is None:
        return
    if chat.type not in ("group", "supergroup"):
        return

    # ذخیره یا آپدیت
    try:
        await repo.get_or_create_group(chat_id=chat.id, title=chat.title)
    except Exception as e:
        logger.warning("ذخیره گروه خطا داد: %s", e)


# ============================================================
#  دستور /setgroup
# ============================================================

async def cmd_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ثبت دستی گروه (فقط تو گروه)."""
    chat = update.effective_chat
    if chat is None or update.message is None:
        return

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("⚠️ این دستور فقط تو گروه کار می‌کنه.")
        return

    await repo.get_or_create_group(chat_id=chat.id, title=chat.title)

    await update.message.reply_text(
        f"✅ این گروه ثبت شد.\n\n"
        f"📌 اسم: {chat.title or 'بدون نام'}\n"
        f"🆔 شناسه: {chat.id}\n\n"
        f"از این به بعد پست‌های تغذیه‌ای اینجا میان."
    )


# ============================================================
#  دستور /groups (فقط ادمین)
# ============================================================

async def cmd_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش لیست گروه‌های ثبت‌شده (فقط ادمین)."""
    user = update.effective_user
    if user is None or update.message is None:
        return

    settings = get_settings()
    if not settings.is_admin(user.id):
        await update.message.reply_text("⛔ این دستور فقط برای ادمین‌هاست.")
        return

    try:
        groups = await repo.list_all_groups()
    except Exception as e:
        logger.warning("لیست گروه‌ها خطا داد: %s", e)
        groups = []

    if not groups:
        await update.message.reply_text(
            "📭 هنوز هیچ گروهی ثبت نشده.\n\n"
            "بات رو به گروه اضافه کن یا /setgroup رو تو گروه بزن."
        )
        return

    lines = [f"📋 **گروه‌های ثبت‌شده ({len(groups)}):**\n"]
    for i, g in enumerate(groups[:30], 1):
        title = g.title or "بدون نام"
        lines.append(f"{i}. {title}\n   `{g.chat_id}`")

    if len(groups) > 30:
        lines.append(f"\n... و {len(groups) - 30} گروه دیگه")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ============================================================
#  دستور /unsetgroup (فقط ادمین)
# ============================================================

async def cmd_unsetgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """حذف گروه از لیست (فقط ادمین)."""
    user = update.effective_user
    if user is None or update.message is None or update.effective_chat is None:
        return

    settings = get_settings()
    if not settings.is_admin(user.id):
        await update.message.reply_text("⛔ فقط ادمین.")
        return

    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("⚠️ این دستور فقط تو گروه کار می‌کنه.")
        return

    try:
        await repo.deactivate_group(chat_id=chat.id)
        await update.message.reply_text("✅ این گروه از لیست پست خودکار حذف شد.")
    except Exception as e:
        logger.warning("حذف گروه خطا داد: %s", e)
        await update.message.reply_text("😔 خطا در حذف گروه.")
