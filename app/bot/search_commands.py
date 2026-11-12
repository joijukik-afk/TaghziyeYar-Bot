"""Search commands handler."""

import logging
from telegram import Update, InputMediaPhoto
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from app.services.web_search_service import get_web_search_service

logger = logging.getLogger(__name__)

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user: return

    query = " ".join(context.args) if context.args else ""
    if not query and update.message.reply_to_message:
        query = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
    
    if not query.strip():
        return await update.message.reply_text(
            "🔍 <b>راهنمای جستجو:</b>\n\n<code>/search قیمت دلار</code>\n<code>/search GTA 6</code>",
            parse_mode="HTML"
        )

    status_msg = await update.message.reply_text(f"🔍 در حال جستجوی عمیق برای: <b>{query[:50]}...</b>", parse_mode="HTML")

    try:
        search_service = get_web_search_service()
        result = await search_service.search_and_answer(query=query, user_id=update.effective_user.id)

        answer_text = result.get("text", "پاسخی یافت نشد.")
        images = result.get("images", [])
        sources = result.get("sources", [])

        final_text = answer_text
        if sources:
            final_text += "\n\n🔗 <b>منابع:</b>\n" + "\n".join([f"• <a href='{s}'>لینک {i+1}</a>" for i, s in enumerate(sources[:3])])

        try: await status_msg.edit_text(final_text, parse_mode="HTML", disable_web_page_preview=True)
        except BadRequest: await status_msg.edit_text(answer_text, disable_web_page_preview=True)

        if images:
            media_group = [InputMediaPhoto(media=img_url) for img_url in images if img_url.startswith("http")]
            if media_group:
                try:
                    await update.message.reply_media_group(media=media_group, caption="🖼️ تصاویر مرتبط")
                except Exception as e:
                    logger.warning(f"Album failed: {e}. Sending individually...")
                    for img in media_group:
                        try: await update.message.reply_photo(photo=img.media)
                        except: continue

    except Exception as e:
        logger.error(f"Search error: {e}")
        await status_msg.edit_text("❌ خطایی در جستجو رخ داد. دوباره تلاش کنید.")
