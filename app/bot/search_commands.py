"""Search commands handler."""

import logging
from telegram import Update, InputMediaPhoto
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from app.services.web_search_service import get_web_search_service

logger = logging.getLogger(__name__)

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return

    query = ""
    if context.args:
        query = " ".join(context.args)
    elif update.message.reply_to_message:
        replied = update.message.reply_to_message
        query = replied.text or replied.caption or ""
    
    if not query.strip():
        return await update.message.reply_text(
            "🔍 <b>راهنمای جستجو:</b>\n\n"
            "یک موضوع یا سوال خود را بعد از دستور بنویسید:\n"
            "<code>/search قیمت دلار امروز</code>\n"
            "<code>/search بهترین مکمل پروتئین</code>",
            parse_mode="HTML"
        )

    status_msg = await update.message.reply_text(f"🔍 در حال جستجوی عمیق برای: <b>{query[:50]}...</b>", parse_mode="HTML")

    try:
        search_service = get_web_search_service()
        result = await search_service.search_and_answer(query=query, user_id=update.effective_user.id)

        answer_text = result.get("text", "متأسفانه پاسخی یافت نشد.")
        images = result.get("images", [])
        sources = result.get("sources", [])

        final_text = answer_text
        if sources:
            final_text += "\n\n🔗 <b>منابع:</b>\n" + "\n".join([f"• <a href='{s}'>لینک {i+1}</a>" for i, s in enumerate(sources[:3])])

        # ارسال متن
        try:
            await status_msg.edit_text(final_text, parse_mode="HTML", disable_web_page_preview=True)
        except BadRequest:
            # اگر HTML مشکل داشت، بدون فرمت می‌فرستیم
            await status_msg.edit_text(answer_text, disable_web_page_preview=True)

        # 👇 ارسال عکس‌ها با مدیریت خطای قوی (سنگین‌ترین بخش)
        if images:
            media_group = []
            for img_url in images:
                media_group.append(InputMediaPhoto(media=img_url))
            
            if media_group:
                try:
                    # تلاش برای ارسال به صورت آلبوم
                    await update.message.reply_media_group(media=media_group, caption="🖼️ تصاویر مرتبط با جستجو")
                except Exception as group_err:
                    logger.warning(f"Group image send failed: {group_err}. Trying individually...")
                    # اگر آلبوم خطا داد، تک تک می‌فرستیم
                    for img in media_group:
                        try:
                            await update.message.reply_photo(photo=img.media)
                        except Exception as single_err:
                            logger.warning(f"Single image failed: {single_err}")
                            continue

    except Exception as e:
        logger.error(f"Search command error: {e}")
        await status_msg.edit_text("❌ متأسفانه در جستجو خطایی پیش آمد. لطفاً دوباره تلاش کنید.")
