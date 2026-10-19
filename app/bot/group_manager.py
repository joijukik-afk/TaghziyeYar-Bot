"""ثبت خودکار گروه‌ها + ارسال به همه گروه‌ها + دستور پست فوری."""

import html
import logging
from telegram import Update, ChatMember
from telegram.ext import ContextTypes

from app.config import get_settings
from app.database import repository as repo
from app.services.image_generator import generate_group_cover # 👈 اضافه شد

logger = logging.getLogger(__name__)

# 🛡️ حافظه موقت (Cache) برای جلوگیری از حمله به دیتابیس
_KNOWN_GROUPS_CACHE = set()


# ============================================================
#  ثبت خودکار
# ============================================================

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """وقتی بات به گروه اضافه شد، chat_id رو ذخیره کن و کاور اختصاصی بفرست."""
    result = update.my_chat_member
    if result is None:
        return

    chat = result.chat
    if chat.type not in ("group", "supergroup"):
        return

    old_status = result.old_chat_member.status if result.old_chat_member else "left"
    new_status = result.new_chat_member.status

    if old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        await repo.get_or_create_group(chat_id=chat.id, title=chat.title)
        _KNOWN_GROUPS_CACHE.add(chat.id) 
        logger.info("✅ بات به گروه اضافه شد: %s (%s)", chat.title, chat.id)

        safe_title = html.escape(chat.title or "دوستان")

        # ۱. ارسال پیام خوش‌آمدگویی
        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=(
                    f"🥗 سلام <b>{safe_title}</b>! من «تغذیه‌یار» هستم.\n\n"
                    "📌 این گروه ثبت شد و از این به بعد\n"
                    "هر ۸ ساعت یه پست تغذیه‌ای اینجا می‌فرستم.\n\n"
                    "برای شروع: /help"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning("ارسال پیام خوشامد خطا داد: %s", e)

        # ۲. 🎨 ساخت و ارسال خودکار عکس اختصاصی گروه
        try:
            await context.bot.send_chat_action(chat_id=chat.id, action="upload_photo")
            group_name = chat.title or "Nutrition Group"
            
            # فراخوانی هوش مصنوعی برای ساخت لینک عکس
            image_url = await generate_group_cover(group_name)
            
            await context.bot.send_photo(
                chat_id=chat.id,
                photo=image_url,
                caption=f"🎨 این هم کاور اختصاصی گروه <b>{safe_title}</b> است که با هوش مصنوعی طراحی شده!",
                parse_mode="HTML"
            )
            logger.info("✅ کاور اختصاصی برای گروه %s ارسال شد.", chat.id)
        except Exception as e:
            # اگر ساخت عکس خطا داد، ربات کرش نمی‌کند و فقط لاگ ثبت می‌شود
            logger.warning("ارسال عکس خودکار به گروه خطا داد: %s", e)


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """از هر پیام تو گروه، chat_id رو ذخیره کن (با بهینه‌سازی امنیتی)."""
    chat = update.effective_chat
    if chat is None:
        return
    if chat.type not in ("group", "supergroup"):
        return

    if chat.id in _KNOWN_GROUPS_CACHE:
        return

    try:
        await repo.get_or_create_group(chat_id=chat.id, title=chat.title)
        _KNOWN_GROUPS_CACHE.add(chat.id)
    except Exception as e:
        logger.warning("ذخیره گروه خطا داد: %s", e)


# ============================================================
#  توابع کمکی امنیتی
# ============================================================

async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """بررسی می‌کند که آیا کاربر دستور زده، ادمین گروه است یا نه."""
    if not update.effective_user or not update.effective_chat:
        return False
        
    if get_settings().is_admin(update.effective_user.id):
        return True

    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        if member.status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER):
            return True
    except Exception:
        pass
    return False


# ============================================================
#  دستور /setgroup
# ============================================================

async def cmd_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ثبت دستی گروه."""
    chat = update.effective_chat
    if chat is None or update.message is None:
        return

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("⚠️ این دستور فقط تو گروه کار می‌کنه.")
        return

    if not await is_group_admin(update, context):
        await update.message.reply_text("⛔ این دستور فقط برای ادمین‌های گروه مجاز است.")
        return

    await repo.get_or_create_group(chat_id=chat.id, title=chat.title)
    _KNOWN_GROUPS_CACHE.add(chat.id)

    safe_title = html.escape(chat.title or 'بدون نام')
    await update.message.reply_text(
        f"✅ این گروه ثبت شد.\n\n"
        f"📌 اسم: {safe_title}\n"
        f"🆔 شناسه: <code>{chat.id}</code>\n\n"
        f"از این به بعد پست‌های تغذیه‌ای اینجا میان.\n"
        f"برای تست فوری: /postnow",
        parse_mode="HTML"
    )


# ============================================================
#  دستور /postnow — ارسال فوری یه پست
# ============================================================

async def cmd_postnow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ارسال فوری یه پست به همین گروه (فقط ادمین)."""
    user = update.effective_user
    chat = update.effective_chat
    if user is None or update.message is None or chat is None:
        return

    if not await is_group_admin(update, context):
        await update.message.reply_text("⛔ این دستور فقط برای ادمین‌هاست.")
        return

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("⚠️ این دستور فقط تو گروه کار می‌کنه.")
        return

    status_msg = await update.message.reply_text("🔄 در حال ساخت پست...")

    from app.services.auto_content import post_auto_content

    try:
        ok = await post_auto_content(context.bot, chat.id)
        if ok:
            try:
                await status_msg.delete()
            except Exception:
                pass
            logger.info("پست فوری به %s ارسال شد.", chat.id)
        else:
            await status_msg.edit_text("😔 خطا در ساخت پست. دوباره تلاش کن.")
    except Exception as e:
        logger.warning("خطا در پست فوری: %s", e)
        try:
            await status_msg.edit_text("😔 خطا در ساخت پست. دوباره تلاش کن.")
        except Exception:
            pass


# ============================================================
#  دستور /groups (فقط ادمین ربات)
# ============================================================

async def cmd_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش لیست گروه‌های ثبت‌شده."""
    user = update.effective_user
    if user is None or update.message is None:
        return

    settings = get_settings()
    if not settings.is_admin(user.id):
        await update.message.reply_text("⛔ این دستور فقط برای ادمین ربات است.")
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

    lines = [f"📋 <b>گروه‌های ثبت‌شده ({len(groups)}):</b>\n"]
    for i, g in enumerate(groups[:30], 1):
        title = html.escape(g.title or "بدون نام")
        lines.append(f"{i}. {title}\n   <code>{g.chat_id}</code>")

    if len(groups) > 30:
        lines.append(f"\n... و {len(groups) - 30} گروه دیگه")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ============================================================
#  دستور /unsetgroup (فقط ادمین)
# ============================================================

async def cmd_unsetgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """حذف گروه از لیست."""
    user = update.effective_user
    if user is None or update.message is None or update.effective_chat is None:
        return

    if not await is_group_admin(update, context):
        await update.message.reply_text("⛔ فقط ادمین‌ها مجاز هستند.")
        return

    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("⚠️ این دستور فقط تو گروه کار می‌کنه.")
        return

    try:
        await repo.deactivate_group(chat_id=chat.id)
        if chat.id in _KNOWN_GROUPS_CACHE:
            _KNOWN_GROUPS_CACHE.remove(chat.id)
        await update.message.reply_text("✅ این گروه از لیست پست خودکار حذف شد.")
    except Exception as e:
        logger.warning("حذف گروه خطا داد: %s", e)
        await update.message.reply_text("😔 خطا در حذف گروه.")
