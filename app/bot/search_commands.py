"""Search commands handler."""

import logging
from telegram import Update
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
        return await update.message.reply_text("🔍 <b>راهنما:</b>\n<code>/search قیمت دلار</code>", parse_mode="HTML")

    status_msg = await update.message.reply_text(f"🔍 در حال جستجو برای: <b>{query[:50]}...</b>", parse_mode="HTML")

    try:
        search_service = get_web_search_service()
        answer = await search_service.search_and_answer(query=query, user_id=update.effective_user.id)

        try: 
            await status_msg.edit_text(answer, parse_mode="HTML", disable_web_page_preview=True)
        except BadRequest: 
            await status_msg.edit_text(answer, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Search error: {e}")
        await status_msg.edit_text("❌ خطایی در جستجو رخ داد.")
