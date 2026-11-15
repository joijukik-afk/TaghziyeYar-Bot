"""ثبت خودکار گروه‌ها + ارسال به همه گروه‌ها + دستور پست فوری."""

import html
import logging
import asyncio
from cachetools import LRUCache
from telegram import Update, ChatMember
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from app.config import get_settings
from app.database import repository as repo
from app.services.image_generator import generate_group_cover 

logger = logging.getLogger(__name__)

_KNOWN_GROUPS_CACHE = LRUCache(maxsize=10000)

async def _send_cover_background(bot, chat_id: int, safe_title: str, group_name: str):
    try:
        await bot.send_chat_action(chat_id=chat_id, action="upload_photo")
        photo_bytes = await generate_group_cover(group_name)
        await bot.send_photo(
            chat_id=chat_id, photo=photo_bytes,
            caption=f"🎨 این هم کاور اختصاصی گروه <b>{safe_title}</b> است.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.warning("ارسال عکس خودکار به گروه خطا داد: %s", e, exc_info=True)

async def on_bot_added(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.my_chat_member
    if result is None: return
    chat = result.chat
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return

    old_status = result.old_chat_member.status if result.old_chat_member else "left"
    new_status = result.new_chat_member.status

    if old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        await repo.get_or_create_group(chat_id=chat.id, title=chat.title)
        _KNOWN_GROUPS_CACHE[chat.id] = True 
        safe_title = html.escape(chat.title or "دوستان")

        try:
            await context.bot.send_message(
                chat_id=chat.id,
                text=f"🥗 سلام <b>{safe_title}</b>! من «تغذیه‌یار» هستم.\n\n"
                     "📌 این گروه ثبت شد و از این به بعد هر ۸ ساعت یه پست تغذیه‌ای اینجا می‌فرستم.\n\n"
                     "برای شروع: /help",
                parse_mode="HTML"
            )
        except Exception: pass

        group_name = chat.title or "Nutrition Group"
        asyncio.create_task(_send_cover_background(context.bot, chat.id, safe_title, group_name))

async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return
    if chat.id in _KNOWN_GROUPS_CACHE: return

    try:
        await repo.get_or_create_group(chat_id=chat.id, title=chat.title)
        _KNOWN_GROUPS_CACHE[chat.id] = True
    except Exception as e:
        logger.warning("ذخیره گروه خطا داد: %s", e)

async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_user or not update.effective_chat: return False
    if get_settings().is_admin(update.effective_user.id): return True
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        if member.status in (ChatMember.ADMINISTRATOR, ChatMember.OWNER): return True
    except Exception as e:
        logger.warning(f"Failed to check admin status: {e}")
    return False

async def cmd_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None or update.message is None: return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await update.message.reply_text("⚠️ این دستور فقط تو گروه کار می‌کنه.")
    if not await is_group_admin(update, context):
        return await update.message.reply_text("⛔ این دستور فقط برای ادمین‌های گروه مجاز است.")

    await repo.get_or_create_group(chat_id=chat.id, title=chat.title)
    _KNOWN_GROUPS_CACHE[chat.id] = True
    safe_title = html.escape(chat.title or 'بدون نام')
    await update.message.reply_text(
        f"✅ این گروه ثبت شد.\n\n📌 اسم: {safe_title}\n🆔 شناسه: <code>{chat.id}</code>",
        parse_mode="HTML"
    )

async def cmd_postnow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not update.effective_user or not update.message or chat is None: return
    if not await is_group_admin(update, context):
        return await update.message.reply_text("⛔ این دستور فقط برای ادمین‌هاست.")
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await update.message.reply_text("⚠️ این دستور فقط تو گروه کار می‌کنه.")

    status_msg = await update.message.reply_text("🔄 در حال ساخت پست...")
    from app.services.auto_content import post_auto_content
    try:
        ok = await post_auto_content(context.bot, chat.id)
        if ok:
            try: await status_msg.delete()
            except Exception: pass
        else:
            await status_msg.edit_text("😔 خطا در ساخت پست. دوباره تلاش کن.")
    except Exception as e:
        logger.warning("خطا در پست فوری: %s", e, exc_info=True)
        try: await status_msg.edit_text("😔 خطا در ساخت پست.")
        except Exception: pass

async def cmd_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.message is None: return
    if not get_settings().is_admin(user.id):
        return await update.message.reply_text("⛔ این دستور فقط برای ادمین ربات است.")

    try: groups = await repo.list_all_groups()
    except Exception: groups = []

    if not groups:
        return await update.message.reply_text("📭 هنوز هیچ گروهی ثبت نشده.")

    lines = [f"📋 <b>گروه‌های ثبت‌شده ({len(groups)}):</b>\n"]
    for i, g in enumerate(groups[:30], 1):
        title = html.escape(g.title or "بدون نام")
        lines.append(f"{i}. {title}\n   <code>{g.chat_id}</code>")
    if len(groups) > 30: lines.append(f"\n... و {len(groups) - 30} گروه دیگه")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def cmd_unsetgroup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if not update.effective_user or not update.message or chat is None: return
    if not await is_group_admin(update, context):
        return await update.message.reply_text("⛔ فقط ادمین‌ها مجاز هستند.")
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return await update.message.reply_text("⚠️ این دستور فقط تو گروه کار می‌کنه.")
    try:
        await repo.deactivate_group(chat_id=chat.id)
        if chat.id in _KNOWN_GROUPS_CACHE: del _KNOWN_GROUPS_CACHE[chat.id]
        await update.message.reply_text("✅ این گروه از لیست پست خودکار حذف شد.")
    except Exception as e:
        logger.warning("حذف گروه خطا داد: %s", e)
        await update.message.reply_text("😔 خطا در حذف گروه.")
