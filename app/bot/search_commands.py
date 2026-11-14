"""Search commands handler with API + Tavily."""

import logging
from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from app.services.agent_search_service import get_agent_search_service
from app.services.ai_service import get_ai_service

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
        agent = get_agent_search_service()
        result_text = await agent.process(query)
        
        # اگر جواب مستقیم بود (قیمت یا کد تخفیف)، همون رو بفرست
        if result_text.startswith(("💰", "🎟️", "⚠️")):
            await status_msg.edit_text(result_text, parse_mode="HTML")
            return
            
        # اگر سوال عمومی بود، به AI بده
        if not result_text:
            await status_msg.edit_text("⚠️ متأسفانه اطلاعاتی پیدا نشد. لطفاً دوباره تلاش کنید.")
            return

        ai = get_ai_service()
        prompt = (
            f"اطلاعات جستجو (از اینترنت):\n{result_text}\n\n"
            f"سوال کاربر: {query}\n\n"
            f"⚠️ دستور: تو باید بر اساس اطلاعات بالا جواب بدهی. اگر در اطلاعات عددی یا کدی وجود دارد، آن را در پاسخ خود ذکر کن. هرگز نگو 'دسترسی ندارم'."
        )
        
        answer, _ = await ai.ask(
            user_message=prompt,
            user_name=update.effective_user.first_name or "کاربر",
            user_id=update.effective_user.id
        )

        try: 
            await status_msg.edit_text(answer, parse_mode="HTML", disable_web_page_preview=True)
        except BadRequest: 
            await status_msg.edit_text(answer, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Search error: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ خطا: <code>{str(e)[:200]}</code>", parse_mode="HTML")
