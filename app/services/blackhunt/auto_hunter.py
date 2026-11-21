"""شکارچی خودکار تخفیف‌های ۹۰٪ و بالاتر — از دیتابیس گروه می‌خونه."""

import asyncio
import logging
import os
from typing import List

from telegram import Bot
from telegram.constants import ParseMode

from app.services.blackhunt.engine import get_engine
from app.services.blackhunt.models import DealResult

logger = logging.getLogger(__name__)


class AutoHunter:
    def __init__(
        self,
        bot_token: str,
        interval_seconds: int = 300,
        min_discount: int = 90,
        fallback_chat_id: str = "",
    ):
        self.bot = Bot(token=bot_token)
        self.interval = interval_seconds
        self.min_discount = min_discount
        self.fallback_chat_id = fallback_chat_id
        self.sent_urls: set = set()

    async def _get_target_chats(self) -> List[str]:
        """
        لیست گروه‌های هدف رو برمی‌گردونه:
        1. گروه‌های ثبت‌شده با /setgroup در دیتابیس
        2. اگه دیتابیس خالی بود، از fallback_chat_id (env) استفاده می‌کنه
        """
        chat_ids: List[str] = []
        try:
            from app.database import repository as repo
            groups = await repo.list_all_groups()
            for g in groups or []:
                if getattr(g, "is_active", True) and getattr(g, "chat_id", None):
                    chat_ids.append(str(g.chat_id))
            if chat_ids:
                logger.info(f"AutoHunter: {len(chat_ids)} گروه از دیتابیس پیدا شد")
        except Exception as e:
            logger.warning(f"AutoHunter: خواندن گروه‌ها از دیتابیس شکست خورد: {e}")

        if not chat_ids and self.fallback_chat_id:
            chat_ids.append(self.fallback_chat_id)
            logger.info(f"AutoHunter: استفاده از fallback_chat_id = {self.fallback_chat_id}")

        return chat_ids

    async def run_forever(self):
        logger.info(
            f"AutoHunter started: min_discount={self.min_discount}%, interval={self.interval}s"
        )
        while True:
            try:
                await self._scan_and_send()
            except Exception as e:
                logger.error(f"AutoHunter loop error: {e}", exc_info=True)
            await asyncio.sleep(self.interval)

    async def _scan_and_send(self):
        chat_ids = await self._get_target_chats()
        if not chat_ids:
            logger.warning("AutoHunter: هیچ گروه هدفی پیدا نشد (نه در DB نه در env) — رد شد")
            return

        engine = get_engine()
        request = f"تخفیف‌های بالای {self.min_discount} درصد بلک فرایدی"
        try:
            deals, stats, _ = await engine.search(request)
        except Exception as e:
            logger.error(f"AutoHunter search failed: {e}")
            return

        if not deals:
            logger.info(f"AutoHunter: در این دور تخفیف {self.min_discount}٪+ پیدا نشد")
            return

        sent_count = 0
        for deal in deals:
            if deal.product_url in self.sent_urls:
                continue
            pct = deal.real_discount_percent or deal.listed_discount_percent or 0
            if pct < self.min_discount:
                continue

            self.sent_urls.add(deal.product_url)
            for chat_id in chat_ids:
                ok = await self._send_deal(deal, chat_id)
                if ok:
                    sent_count += 1
                await asyncio.sleep(1.5)  # جلوگیری از محدودیت تلگرام

        if sent_count > 0:
            logger.info(f"AutoHunter: {sent_count} پیام تخفیف ارسال شد")
        else:
            logger.info("AutoHunter: تخفیف جدیدی برای ارسال نبود")

    async def _send_deal(self, deal: DealResult, chat_id: str) -> bool:
        pct = deal.real_discount_percent or deal.listed_discount_percent or 0
        text = (
            f"🔥 <b>شکار تخفیف {pct}%!</b>\n\n"
            f"🛍️ <b>{deal.product_name}</b>\n"
            f"🏬 فروشگاه: {deal.store}\n"
            f"💰 قیمت: <b>{deal.current_price:,} تومان</b>"
            + (f" (قبلی: {deal.listed_old_price:,})" if deal.listed_old_price else "")
            + "\n"
            f"🔗 <a href='{deal.product_url}'>مشاهده و خرید</a>"
        )
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
            )
            logger.info(f"AutoHunter: تخفیف ارسال شد به {chat_id}")
            return True
        except Exception as e:
            logger.error(f"AutoHunter: ارسال به {chat_id} شکست خورد: {e}")
            return False


_auto_hunter = None


def get_auto_hunter() -> AutoHunter:
    global _auto_hunter
    if _auto_hunter is None:
        # 👈 توکن رو از اسم‌های مختلف env امتحان می‌کنیم
        token = (
            os.getenv("TELEGRAM_BOT_TOKEN")
            or os.getenv("BOT_TOKEN")
            or os.getenv("TG_BOT_TOKEN")
            or ""
        )
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN در env تنظیم نشده")

        # fallback اختیاری — اگه دیتابیس خالی بود
        fallback = os.getenv("DEAL_CHAT_ID", "").strip()

        _auto_hunter = AutoHunter(
            bot_token=token,
            interval_seconds=300,
            min_discount=90,
            fallback_chat_id=fallback,
        )
    return _auto_hunter
