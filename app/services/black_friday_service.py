"""سرویس جستجوی هدفمند تخفیف‌های بلک‌فرایدی در فروشگاه‌های ایرانی."""

import logging
import asyncio
import re
from typing import List, Dict, Optional
from dataclasses import dataclass
from tavily import TavilyClient

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class DealResult:
    product_name: str
    store: str
    original_price: Optional[int]
    discounted_price: Optional[int]
    discount_percent: Optional[int]
    product_url: str


class BlackFridayService:
    """جستجوی تخفیف در فروشگاه‌های ایرانی با Tavily."""

    STORES = {
        "digikala": "digikala.com",
        "snappshop": "snappshop.ir",
        "technolife": "technolife.com",
        "banimode": "banimode.com",
        "khanoumi": "khanoumi.com",
        "janebi": "janebi.com",
        "digistyle": "digistyle.com",
        "torob": "torob.com",
    }

    def __init__(self):
        settings = get_settings()
        self.tavily_key = settings.tavily_api_key
        self.tavily = TavilyClient(api_key=self.tavily_key) if self.tavily_key else None

    async def search_deals(self, query: str, max_stores: int = 4) -> List[DealResult]:
        """جستجوی تخفیف برای یک محصول در فروشگاه‌های مختلف."""
        if not self.tavily:
            return []

        results: List[DealResult] = []
        store_items = list(self.STORES.items())[:max_stores]

        async def _search_one(store_key: str, domain: str) -> Optional[DealResult]:
            try:
                tavily_query = f"site:{domain} {query} تخفیف بلک فرایدی قیمت"
                res = await asyncio.to_thread(
                    self.tavily.search,
                    query=tavily_query,
                    search_depth="advanced",
                    max_results=3,
                )
                items = res.get("results", [])
                if not items:
                    return None

                best = items[0]
                url = best.get("url", "")
                if not url or domain not in url:
                    return None

                content = (best.get("content", "") + " " + best.get("title", ""))
                prices = self._extract_prices(content)
                original, discounted, percent = self._parse_prices(prices)

                return DealResult(
                    product_name=best.get("title", query)[:120],
                    store=store_key,
                    original_price=original,
                    discounted_price=discounted,
                    discount_percent=percent,
                    product_url=url,
                )
            except Exception as e:
                logger.warning(f"BlackFriday search failed for {domain}: {e}")
                return None

        tasks = [_search_one(k, d) for k, d in store_items]
        found = await asyncio.gather(*tasks, return_exceptions=True)

        for item in found:
            if isinstance(item, DealResult):
                results.append(item)

        return results

    def _extract_prices(self, text: str) -> List[int]:
        """استخراج اعداد قیمت از متن."""
        patterns = [
            r"([۰-۹]{1,3}(?:[,،.][۰-۹]{3})+)",
            r"([0-9]{1,3}(?:[,،.][0-9]{3})+)",
            r"([0-9]{5,9})",
            r"([۰-۹]{5,9})",
        ]
        found = []
        for p in patterns:
            for match in re.findall(p, text):
                clean = (
                    match.replace(",", "")
                    .replace("،", "")
                    .replace(".", "")
                    .translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
                )
                try:
                    val = int(clean)
                    if 10_000 < val < 500_000_000:
                        found.append(val)
                except ValueError:
                    pass
        return found

    def _parse_prices(self, prices: List[int]) -> tuple[Optional[int], Optional[int], Optional[int]]:
        """تشخیص قیمت قبل و بعد از تخفیف."""
        if len(prices) < 2:
            return (None, None, None)

        unique = sorted(set(prices), reverse=True)
        original = unique[0]
        discounted = unique[-1]

        if original <= discounted:
            return (None, None, None)

        percent = round((1 - discounted / original) * 100)
        if percent <= 0 or percent > 90:
            return (None, None, None)

        return (original, discounted, percent)

    async def compare_prices(self, product_name: str) -> Dict[str, List[DealResult]]:
        """مقایسه قیمت یک محصول در فروشگاه‌های مختلف."""
        deals = await self.search_deals(product_name, max_stores=len(self.STORES))
        grouped: Dict[str, List[DealResult]] = {}
        for deal in deals:
            grouped.setdefault(deal.store, []).append(deal)
        return grouped

    def format_deals(self, deals: List[DealResult], title: str = "بهترین تخفیف‌ها") -> str:
        """تبدیل نتایج به متن آماده‌ی ارسال."""
        if not deals:
            return "⚠️ متأسفانه تخفیف فعالی برای این محصول پیدا نکردم. لطفاً نام محصول را دقیق‌تر وارد کنید یا نام فروشگاه را مشخص کنید."

        lines = [f"🛍️ <b>{title}:</b>\n"]
        for deal in deals[:6]:
            price_line = ""
            if deal.discounted_price and deal.original_price:
                price_line = (
                    f"  💰 قیمت: {deal.discounted_price:,} تومان"
                    f" (<s>{deal.original_price:,}</s>) — {deal.discount_percent}٪ تخفیف\n"
                )
            elif deal.discounted_price:
                price_line = f"  💰 قیمت: {deal.discounted_price:,} تومان\n"

            lines.append(
                f"• <b>{deal.product_name}</b> از {deal.store}\n"
                f"{price_line}"
                f"  🔗 <a href='{deal.product_url}'>مشاهده محصول</a>\n"
            )
        return "\n".join(lines)


_black_friday_service: Optional[BlackFridayService] = None


def get_black_friday_service() -> BlackFridayService:
    global _black_friday_service
    if _black_friday_service is None:
        _black_friday_service = BlackFridayService()
    return _black_friday_service
