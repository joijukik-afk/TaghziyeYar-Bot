"""هندلر دستور /sticker برای ساخت استیکر از متن فارسی"""
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.services.sticker_service import create_sticker

logger = logging.getLogger(__name__)

STYLES = ("dark", "light", "transparent", "gradient")


async def cmd_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    args = list(context.args or [])

    # اگر اولین کلمه یک استایل بود، آن را جدا کن
    style = "dark"
    if args and args[0].lower() in STYLES:
        style = args[0].lower()
        args = args[1:]

    # متن: از آرگومان‌ها یا از ریپلای
    text = " ".join(args).strip()
    if not text and update.message.reply_to_message:
        text = (update.message.reply_to_message.text or "").strip()

    if not text:
        await update.message.reply_text(
            "🖼 طرز استفاده:\n\n"
            "• `/sticker متن شما`\n"
            "• `/sticker light متن شما`\n"
            "• یا ریپلای روی یک پیام بنویسید: `/sticker`\n\n"
            "استایل‌ها: `dark` | `light` | `transparent` | `gradient`",
            parse_mode="Markdown",
        )
        return

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.UPLOAD_PHOTO,
        )
    except Exception:
        pass

    try:
        sticker_buf = create_sticker(text, style=style)
        await update.message.reply_sticker(sticker=sticker_buf)
    except Exception as e:
        logger.error(f"sticker creation failed: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ متأسفانه ساخت استیکر با خطا مواجه شد."
        )
