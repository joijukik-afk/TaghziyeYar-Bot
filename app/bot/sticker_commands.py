"""هندلر دستور /sticker — ساخت استیکر از متن فارسی.

این فایل کاملاً مستقل است:
- از app.services.sticker_service تابع create_sticker را می‌خواند
- تابع cmd_sticker را تعریف می‌کند که main.py انتظارش را دارد
- نیازی به app.handlers.sticker ندارد (اگر هم باشد، تداخلی نیست)
"""
import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from app.services.sticker_service import create_sticker

logger = logging.getLogger(__name__)

# استایل‌های مجاز
STYLES = ("dark", "light", "transparent", "gradient")
DEFAULT_STYLE = "dark"
MAX_TEXT_LENGTH = 200


async def cmd_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /sticker <متن> — ساخت استیکر ۵۱۲×۵۱۲ از متن فارسی."""
    if not update.message:
        return

    args = list(context.args or [])

    # تشخیص استایل: اگر اولین کلمه یکی از استایل‌ها بود
    style = DEFAULT_STYLE
    if args and args[0].lower() in STYLES:
        style = args[0].lower()
        args = args[1:]

    # متن: از آرگومان‌ها، وگرنه از ریپلای
    text = " ".join(args).strip()
    if not text and update.message.reply_to_message:
        text = (update.message.reply_to_message.text or "").strip()

    # اگر متنی نبود، راهنما نشان بده
    if not text:
        await update.message.reply_text(
            "🖼 <b>ساخت استیکر فارسی</b>\n\n"
            "• <code>/sticker متن شما</code>\n"
            "• <code>/sticker light متن شما</code>\n"
            "• یا ریپلای روی یک پیام بنویسید: <code>/sticker</code>\n\n"
            "🎨 <b>استایل‌ها:</b>\n"
            "• <code>dark</code> — پس‌زمینه‌ی تیره (پیش‌فرض)\n"
            "• <code>light</code> — پس‌زمینه‌ی روشن\n"
            "• <code>transparent</code> — پس‌زمینه‌ی شفاف\n"
            "• <code>gradient</code> — گرادیانت بنفش",
            parse_mode="HTML",
        )
        return

    # محدودیت طول متن
    if len(text) > MAX_TEXT_LENGTH:
        await update.message.reply_text(
            f"❌ متن شما خیلی بلند است. حداکثر {MAX_TEXT_LENGTH} کاراکتر مجاز است."
        )
        return

    # نمایش وضعیت «در حال آپلود»
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.UPLOAD_PHOTO,
        )
    except Exception:
        pass

    # ساخت و ارسال استیکر
    try:
        sticker_buf = create_sticker(text, style=style)
        await update.message.reply_sticker(sticker=sticker_buf)
        logger.info(f"sticker sent: style={style} len={len(text)}")
    except Exception as e:
        logger.error(f"sticker creation failed: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ متأسفانه ساخت استیکر با خطا مواجه شد.\n"
            "لطفاً دوباره تلاش کنید."
        )
