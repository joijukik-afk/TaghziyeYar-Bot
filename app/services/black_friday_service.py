"""سرویس پیشرفته بلک‌فرایدی — با اعتبارسنجی URL و جلوگیری از لینک جعلی."""

import logging
import asyncio
import re
import json
import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

import httpx
from tavily import TavilyClient

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class DealResult:
    product_name: str
    store: str
    product_url: str
    original_price: Optional[int] = None
    discounted_price: Optional[int] = None
    discount_percent: Optional[int] = None
    seller: Optional[str] = None
    warranty: Optional[str] = None
    availability: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    image_url: Optional[str] = None


@dataclass
class SearchStats:
    total_found: int = 0
    stores_searched: int = 0
    stores_with_results: int = 0
    best_discount_percent: Optional[int] = None
    best_price: Optional[int] = None
    search_duration_seconds: float = 0.0
    timestamp: str = ""


class BlackFridayService:
    """موتور جستجوی تخفیف بلک‌فرایدی با اعتبارسنجی لینک محصول."""

    PRODUCT_URL_PATTERNS = {
        "digikala.com": r"^https?://(www\.)?digikala\.com/product/dkp-\d+",
        "torob.com": r"^https?://(www\.)?torob\.com/p/[a-zA-Z0-9]+",
        "snappshop.ir": r"^https?://(www\.)?snappshop\.ir/product/\d+",
        "technolife.com": r"^https?://(www\.)?technolife\.com/product/[a-z0-9\-]+",
        "banimode.com": r"^https?://(www\.)?banimode\.com/product/[a-z0-9\-]+",
        "janebi.com": r"^https?://(www\.)?janebi\.com/product/[a-z0-9\-]+",
        "khanoumi.com": r"^https?://(www\.)?khanoumi\.com/product/[a-z0-9\-]+",
        "digistyle.com": r"^https?://(www\.)?digistyle\.com/product/[a-z0-9\-]+",
        "modiseh.com": r"^https?://(www\.)?modiseh\.com/product/[a-z0-9\-]+",
        "basalam.com": r"^https?://(www\.)?basalam\.com/product/\d+",
        "okala.com": r"^https?://(www\.)?okala\.com/product/[a-z0-9\-]+",
    }

    STORES = {
        "digikala": {"domain": "digikala.com", "category": "digital"},
        "technolife": {"domain": "technolife.com", "category": "digital"},
        "janebi": {"domain": "janebi.com", "category": "digital"},
        "torob": {"domain": "torob.com", "category": "digital"},
        "zanbil": {"domain": "zanbil.ir", "category": "digital"},
        "emalls": {"domain": "emalls.ir", "category": "digital"},
        "banimode": {"domain": "banimode.com", "category": "fashion"},
        "digistyle": {"domain": "digistyle.com", "category": "fashion"},
        "modiseh": {"domain": "modiseh.com", "category": "fashion"},
        "shixon": {"domain": "shixon.com", "category": "fashion"},
        "khanoumi": {"domain": "khanoumi.com", "category": "beauty"},
        "basalam": {"domain": "basalam.com", "category": "general"},
        "snappshop": {"domain": "snappshop.ir", "category": "grocery"},
        "okala": {"domain": "okala.com", "category": "grocery"},
    }

    def __init__(self):
        settings = get_settings()
        self.tavily_key = settings.tavily_api_key
        self.tavily = TavilyClient(api_key=self.tavily_key) if self.tavily_key else None
        self._http = httpx.AsyncClient(
            timeout=15.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
            },
        )

    async def close(self):
        await self._http.aclose()

    def _is_valid_product_url(self, url: str) -> bool:
        if not url or not url.startswith(("http://", "https://")):
            return False
        fake_ids = ["1234567", "123456", "000000", "111111", "example"]
        if any(fid in url for fid in fake_ids):
            return False
        for domain, pattern in self.PRODUCT_URL_PATTERNS.items():
            if domain in url:
                return bool(re.match(pattern, url, re.IGNORECASE))
        product_paths = ["/product/", "/p/", "/dp/", "/dkp-", "/item/", "/goods/"]
        return any(p in url.lower() for p in product_paths)

    def _extract_store_from_url(self, url: str) -> str:
        for store_key, store_config in self.STORES.items():
            if store_config.get("domain") and store_config["domain"] in url:
                return store_key
        return url.split("//")[-1].split("/")[0].replace("www.", "").split(".")[0]

    def _extract_prices_from_text(self, text: str) -> List[int]:
        if not text:
            return []
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
                    match.replace(",", "").replace("،", "").replace(".", "")
                    .translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
                )
                try:
                    val = int(clean)
                    if 10_000 < val < 500_000_000:
                        found.append(val)
                except ValueError:
                    pass
        return found

    def _parse_prices(self, prices: List[int]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
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

    async def _search_with_tavily_extract(
        self, query: str, domain: str, store_key: str
    ) -> List[DealResult]:
        if not self.tavily:
            return []
        results = []
        try:
            tavily_query = f"site:{domain} {query} قیمت خرید تخفیف"
            res = await asyncio.to_thread(
                self.tavily.search,
                query=tavily_query,
                search_depth="advanced",
                max_results=6,
            )
            urls = [r.get("url", "") for r in res.get("results", []) if r.get("url")]
            urls = [u for u in urls if self._is_valid_product_url(u)]
            if not urls:
                return []

            extract_res = await asyncio.to_thread(
                self.tavily.extract,
                urls=urls[:3],
            )
            for item in extract_res.get("results", []):
                url = item.get("url", "")
                content = item.get("raw_content", "") or item.get("content", "")
                if not url or not content:
                    continue
                if not self._is_valid_product_url(url):
                    continue
                prices = self._extract_prices_from_text(content)
                original, discounted, percent = self._parse_prices(prices)
                title = item.get("title", "") or query
                results.append(DealResult(
                    product_name=title[:100],
                    store=store_key,
                    product_url=url,
                    original_price=original,
                    discounted_price=discounted,
                    discount_percent=percent,
                    availability="بررسی در صفحه محصول",
                ))
        except Exception as e:
            logger.warning(f"Tavily extract failed for {store_key}: {e}")
        return results

    async def _search_generic_tavily(self, query: str) -> List[DealResult]:
        if not self.tavily:
            return []
        results = []
        try:
            tavily_query = f"خرید {query} تخفیف بلک فرایدی قیمت سایت فروشگاهی ایران"
            res = await asyncio.to_thread(
                self.tavily.search,
                query=tavily_query,
                search_depth="advanced",
                max_results=10,
            )
            for item in res.get("results", []):
                url = item.get("url", "")
                content = item.get("content", "")
                if not url or not content:
                    continue
                if not self._is_valid_product_url(url):
                    continue
                prices = self._extract_prices_from_text(content)
                original, discounted, percent = self._parse_prices(prices)
                store_name = self._extract_store_from_url(url)
                results.append(DealResult(
                    product_name=item.get("title", query)[:100],
                    store=store_name,
                    product_url=url,
                    original_price=original,
                    discounted_price=discounted,
                    discount_percent=percent,
                ))
        except Exception as e:
            logger.warning(f"Generic Tavily search failed: {e}")
        return results

    async def _search_digikala(self, query: str) -> List[DealResult]:
        results = []
        try:
            url = f"https://api.digikala.com/v1/search/?q={query}&page=1"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                "Accept": "application/json",
                "x-web-client": "desktop",
                "x-web-version": "1",
                "Referer": "https://www.digikala.com/",
            }
            resp = await self._http.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"Digikala API returned {resp.status_code}")
                return results
            data = resp.json()
            products = data.get("data", {}).get("products", [])
            for p in products[:5]:
                product_id = p.get("id")
                if not product_id:
                    continue
                product_url = f"https://www.digikala.com/product/dkp-{product_id}/"
                if not self._is_valid_product_url(product_url):
                    continue
                price_info = p.get("default_variant", {}).get("price", {})
                original = price_info.get("rrp_price")
                discounted = price_info.get("selling_price")
                discount = None
                if original and discounted and original > discounted:
                    discount = round((1 - discounted / original) * 100)
                results.append(DealResult(
                    product_name=p.get("title", query)[:100],
                    store="digikala",
                    product_url=product_url,
                    original_price=original,
                    discounted_price=discounted,
                    discount_percent=discount,
                    seller=p.get("default_variant", {}).get("seller", {}).get("title"),
                    availability="موجود" if p.get("default_variant", {}).get("status") == "marketable" else "ناموجود",
                    rating=p.get("rating", {}).get("rate"),
                    review_count=p.get("rating", {}).get("count"),
                ))
        except Exception as e:
            logger.warning(f"Digikala API search failed: {e}")
        return results

    async def search_deals(
        self, query: str, max_results_per_store: int = 3
    ) -> Tuple[List[DealResult], SearchStats]:
        import time
        start_time = time.time()
        tasks = [
            self._search_digikala(query),
            self._search_generic_tavily(query),
        ]
        for store_key, store_config in self.STORES.items():
            if store_key == "digikala":
                continue
            if store_config.get("domain"):
                tasks.append(
                    self._search_with_tavily_extract(query, store_config["domain"], store_key)
                )

        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        merged: List[DealResult] = []
        seen_urls = set()
        for result_list in all_results:
            if isinstance(result_list, Exception):
                logger.warning(f"Search task exception: {result_list}")
                continue
            for deal in result_list:
                if deal.product_url in seen_urls:
                    continue
                if not self._is_valid_product_url(deal.product_url):
                    logger.warning(f"Skipping invalid URL: {deal.product_url}")
                    continue
                seen_urls.add(deal.product_url)
                merged.append(deal)

        merged.sort(key=lambda d: (-(d.discount_percent or 0), d.discounted_price or 10**12))
        merged = merged[: max_results_per_store * 6]

        stats = SearchStats(
            total_found=len(merged),
            stores_searched=len(self.STORES),
            stores_with_results=len({d.store for d in merged}),
            best_discount_percent=max((d.discount_percent for d in merged if d.discount_percent), default=None),
            best_price=min((d.discounted_price for d in merged if d.discounted_price), default=None),
            search_duration_seconds=round(time.time() - start_time, 2),
            timestamp=datetime.datetime.now().isoformat(),
        )
        return merged, stats

    def format_deals(self, deals: List[DealResult], stats: SearchStats, query: str) -> str:
        if not deals:
            return (
                f"🛍️ <b>جستجوی بلک‌فرایدی برای «{query}»</b>\n\n"
                f"⚠️ متأسفانه تخفیف فعالی پیدا نکردم.\n"
                f"📊 {stats.stores_searched} فروشگاه بررسی شد | ⏱ {stats.search_duration_seconds} ثانیه\n\n"
                f"💡 نام دقیق‌تر یا برند محصول را بنویسید."
            )
        lines = [f"🛍️ <b>بهترین تخفیف‌های بلک‌فرایدی برای «{query}»</b>\n"]
        lines.append(
            f"📊 <b>آمار:</b> {stats.total_found} محصول از {stats.stores_with_results} فروشگاه | ⏱ {stats.search_duration_seconds} ثانیه\n"
        )
        if stats.best_discount_percent:
            lines.append(
                f"🏆 <b>بهترین تخفیف:</b> {stats.best_discount_percent}٪"
            )
            if stats.best_price:
                lines[-1] += f" | 💰 <b>کمترین قیمت:</b> {stats.best_price:,} تومان"
            lines[-1] += "\n"
        lines.append("─" * 30 + "\n")

        for i, deal in enumerate(deals[:8], 1):
            price_line = ""
            if deal.discounted_price and deal.original_price:
                price_line = (
                    f"  💰 {deal.discounted_price:,} تومان "
                    f"(<s>{deal.original_price:,}</s>) — <b>{deal.discount_percent}٪ تخفیف</b>\n"
                )
            elif deal.discounted_price:
                price_line = f"  💰 {deal.discounted_price:,} تومان\n"
            extra = ""
            if deal.rating:
                extra += f"  ⭐ {deal.rating}"
                if deal.review_count:
                    extra += f" ({deal.review_count} نظر)"
                extra += "\n"
            if deal.seller:
                extra += f"  🏪 {deal.seller}\n"
            if deal.availability:
                extra += f"  📦 {deal.availability}\n"

            lines.append(
                f"{i}. <b>{deal.product_name}</b>\n"
                f"  🏬 {deal.store}\n"
                f"{price_line}{extra}"
                f"  🔗 <a href='{deal.product_url}'>مشاهده و خرید</a>\n"
            )
        if len(deals) > 8:
            lines.append(f"\n➕ {len(deals) - 8} نتیجه دیگر...")
        lines.append(
            f"\n📅 <i>بلک‌فرایدی ۱۴۰۵: جمعه ۶ آذر — حراج‌ها از ۱ آذر</i>"
        )
        return "\n".join(lines)


_black_friday_service: Optional[BlackFridayService] = None


def get_black_friday_service() -> BlackFridayService:
    global _black_friday_service
    if _black_friday_service is None:
        _black_friday_service = BlackFridayService()
    return _black_friday_service
