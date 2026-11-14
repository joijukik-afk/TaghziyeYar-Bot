"""Search commands handler."""

import logging
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from app.services.agent_search_service import get_agent_search_service

logger = logging.getLogger(__name__)

async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user: return

    query = " ".join(context.args) if context.args else ""
    if not query and update.message.reply_to_message:
        query = update.message.reply_to_message.text or update.message.reply_to_message.caption or ""
    
    if not query.strip():
        return await update.message.reply_text("🔍 <b>راهنما:</b>\n<code>/search قیمت دلار</code>", parse_mode="HTML")

    status_msg = await update.message.reply_text(f"🧠 در حال جستجو برای: <b>{query[:50]}...</b>", parse_mode="HTML")

    try:
        agent = get_agent_search_service()
        answer = await agent.execute_agentic_search(query=query, user_id=update.effective_user.id)
        
        # 👇 اگه جواب خالی بود، پیام مناسب بده
        if not answer or not answer.strip():
            answer = "🔍 متأسفانه اطلاعات دقیقی از منابع آنلاین دریافت نشد.\n\n💡 لطفاً دوباره تلاش کن یا سوالت رو دقیق‌تر بپرس."
        
        try: 
            await status_msg.edit_text(answer, parse_mode="HTML", disable_web_page_preview=True)
        except BadRequest: 
            await status_msg.edit_text(answer, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Search command error: {e}", exc_info=True)
        # 👇 نمایش متن واقعی خطا برای دیباگ
        await status_msg.edit_text(f"❌ خطا در جستجو:\n\n<code>{str(e)[:300]}</code>", parse_mode="HTML")
