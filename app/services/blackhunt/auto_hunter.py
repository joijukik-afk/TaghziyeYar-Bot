"""شکارچی خودکار تخفیف‌های ۹۰٪ و بالاتر."""
import asyncio, logging, os
from datetime import datetime
from telegram import Bot
from telegram.constants import ParseMode
from app.services.blackhunt.engine import get_engine
from app.services.blackhunt.models import DealResult

logger = logging.getLogger(__name__)

class AutoHunter:
    def __init__(self, bot_token: str, chat_id: str, interval_seconds: int = 300, min_discount: int = 90):
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.interval = interval_seconds
        self.min_discount = min_discount
        self.sent_urls: set = set()

    async def run_forever(self):
        logger.info(f"AutoHunter started: min_discount={self.min_discount}%, interval={self.interval}s")
        while True:
            try:
                await self._scan_and_send()
            except Exception as e:
                logger.error(f"AutoHunter loop error: {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    async def _scan_and_send(self):
        engine = get_engine()
        # درخواست عمومی برای تخفیف‌های بالا
        request = f"تخفیف‌های بالای {self.min_discount} درصد بلک فرایدی"
        deals, stats, _ = await engine.search(request)
        if not deals:
            return
        for deal in deals:
            if deal.product_url in self.sent_urls:
                continue
            pct = deal.real_discount_percent or deal.listed_discount_percent or 0
            if pct < self.min_discount:
                continue
            self.sent_urls.add(deal.product_url)
            await self._send_deal(deal)
            await asyncio.sleep(1.5)  # جلوگیری از محدودیت تلگرام

    async def _send_deal(self, deal: DealResult):
        text = (
            f"🔥 <b>شکار تخفیف {deal.listed_discount_percent or deal.real_discount_percent}%!</b>\n\n"
            f"🛍️ <b>{deal.product_name}</b>\n"
            f"🏬 فروشگاه: {deal.store}\n"
            f"💰 قیمت: <b>{deal.current_price:,} تومان</b>"
            + (f" (قبلی: {deal.listed_old_price:,})" if deal.listed_old_price else "") + "\n"
            f"🔗 <a href='{deal.product_url}'>مشاهده و خرید</a>"
        )
        try:
            await self.bot.send_message(chat_id=self.chat_id, text=text, parse_mode=ParseMode.HTML, disable_web_page_preview=False)
            logger.info(f"Sent deal: {deal.product_url}")
        except Exception as e:
            logger.error(f"Failed to send deal: {e}")

_auto_hunter = None
def get_auto_hunter() -> AutoHunter:
    global _auto_hunter
    if _auto_hunter is None:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("DEAL_CHAT_ID", "")
        if not token or not chat_id:
            raise RuntimeError("TELEGRAM_BOT_TOKEN and DEAL_CHAT_ID must be set")
        _auto_hunter = AutoHunter(token, chat_id)
    return _auto_hunter
