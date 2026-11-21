"""سرویس پیشرفته بلک‌فرایدی — جستجوی هوشمند محصول و تخفیف‌های عمومی."""

import logging
import asyncio
import re
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
    availability: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None


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
    """موتور جستجوی تخفیف بلک‌فرایدی با تشخیص قصد کاربر."""

    PRODUCT_URL_PATTERNS = {
        "digikala.com": r"^https?://(www\.)?digikala\.com/product/dkp-\d+",
        "torob.com": r"^https?://(www\.)?torob\.com/p/[a-zA-Z0-9]+",
        "snappshop.ir": r"^https?://(www\.)?snappshop\.ir/product/\d+",
        "technolife.com": r"^https?://(www\.)?technolife\.com/product/[a-z0-9\-]+",
        "banimode.com": r"^https?://(www\.)?banimode\.com/product/[a-z0-9\-]+",
        "janebi.com": r"^https?://(www\.)?janebi\.com/product/[a-z0-9\-]+",
    }

    GENERAL_DEAL_KEYWORDS = [
        "چه چیزی", "چه چیزهایی", "چی تخفیف", "چی‌ها تخفیف", "لیست تخفیف",
        "همه تخفیف", "تخفیف‌ها", "تخفیف ها", "حراجی‌ها", "حراج ها",
        "محصولات تخفیف", "کالاهای تخفیف", "پیشنهاد ویژه", "شگفت‌انگیز",
        "تخفیف خورده", "تخفیف‌خورده",
    ]

    DISCOUNT_PERCENT_PATTERN = re.compile(
        r"(\d{2,3})\s*(?:درصد|٪|%|percent)", re.IGNORECASE
    )

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

    def _is_general_deal_query(self, query: str) -> bool:
        q_lower = query.lower().strip()
        if any(kw in q_lower for kw in self.GENERAL_DEAL_KEYWORDS):
            return True
        if self.DISCOUNT_PERCENT_PATTERN.search(q_lower):
            return True
        return False

    def _extract_min_discount(self, query: str) -> Optional[int]:
        match = self.DISCOUNT_PERCENT_PATTERN.search(query)
        if match:
            try:
                val = int(match.group(1))
                if 1 <= val <= 100:
                    return val
            except ValueError:
                pass
        return None

    def _is_valid_product_url(self, url: str) -> bool:
        if not url or not url.startswith(("http://", "https://")):
            return False
        fake_ids = ["1234567", "123456", "000000", "111111", "example"]
        if any(fid in url for fid in fake_ids):
            return False
        for domain, pattern in self.PRODUCT_URL_PATTERNS.items():
            if domain in url:
                return bool(re.match(pattern, url, re.IGNORECASE))
        product_paths = ["/product/", "/p/", "/dp/", "/dkp-", "/item/"]
        return any(p in url.lower() for p in product_paths)

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

    async def _fetch_digikala_incredible_offers(
        self, min_discount: Optional[int] = None, max_results: int = 10
    ) -> List[DealResult]:
        results = []
        try:
            url = "https://api.digikala.com/v1/incredible-offers/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                "Accept": "application/json",
                "x-web-client": "desktop",
                "x-web-version": "1",
                "Referer": "https://www.digikala.com/",
            }
            resp = await self._http.get(url, headers=headers)
            if resp.status_code != 200:
                return await self._fetch_digikala_deals_via_search(min_discount, max_results)
            data = resp.json()
            products = data.get("data", {}).get("products", []) or data.get("data", {}).get("incredible_offers", [])
            if not products:
                return await self._fetch_digikala_deals_via_search(min_discount, max_results)
            for p in products[:max_results]:
                product_id = p.get("id")
                if not product_id:
                    continue
                product_url = f"https://www.digikala.com/product/dkp-{product_id}/"
                if not self._is_valid_product_url(product_url):
                    continue
                price_info = p.get("default_variant", {}).get("price", {})
                original = price_info.get("rrp_price")
                discounted = price_info.get("selling_price")
                discount = p.get("discount_percent") or p.get("discount_pct")
                if discount is None and original and discounted and original > discounted:
                    discount = round((1 - discounted / original) * 100)
                if min_discount is not None and (discount or 0) < min_discount:
                    continue
                results.append(DealResult(
                    product_name=p.get("title_fa") or p.get("title", "")[:100],
                    store="digikala",
                    product_url=product_url,
                    original_price=original,
                    discounted_price=discounted,
                    discount_percent=discount,
                    seller="دیجی‌کالا",
                    availability="موجود",
                    rating=p.get("rating", {}).get("rate"),
                    review_count=p.get("rating", {}).get("count"),
                ))
        except Exception as e:
            logger.warning(f"Digikala incredible offers fetch failed: {e}")
            return await self._fetch_digikala_deals_via_search(min_discount, max_results)
        return results

    async def _fetch_digikala_deals_via_search(
        self, min_discount: Optional[int] = None, max_results: int = 10
    ) -> List[DealResult]:
        results = []
        try:
            url = "https://api.digikala.com/v1/search/?q=&sort=7&page=1"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                "Accept": "application/json",
                "x-web-client": "desktop",
                "x-web-version": "1",
                "Referer": "https://www.digikala.com/",
            }
            resp = await self._http.get(url, headers=headers)
            if resp.status_code != 200:
                return results
            data = resp.json()
            products = data.get("data", {}).get("products", [])
            for p in products[:max_results]:
                product_id = p.get("id")
                if not product_id:
                    continue
                product_url = f"https://www.digikala.com/product/dkp-{product_id}/"
                if not self._is_valid_product_url(product_url):
                    continue
                price_info = p.get("default_variant", {}).get("price", {})
                original = price_info.get("rrp_price")
                discounted = price_info.get("selling_price")
                discount = p.get("discount_percent")
                if discount is None and original and discounted and original > discounted:
                    discount = round((1 - discounted / original) * 100)
                if min_discount is not None and (discount or 0) < min_discount:
                    continue
                results.append(DealResult(
                    product_name=p.get("title_fa") or p.get("title", "")[:100],
                    store="digikala",
                    product_url=product_url,
                    original_price=original,
                    discounted_price=discounted,
                    discount_percent=discount,
                    availability="موجود",
                ))
        except Exception as e:
            logger.warning(f"Digikala search fallback failed: {e}")
        return results

    async def _fetch_torob_offers(
        self, min_discount: Optional[int] = None, max_results: int = 10
    ) -> List[DealResult]:
        results = []
        try:
            url = "https://api.torob.com/v4/special-offers/"
            resp = await self._http.get(url)
            if resp.status_code != 200:
                return results
            data = resp.json()
            products = data.get("results", []) or data.get("products", [])
            for p in products[:max_results]:
                product_id = p.get("id") or p.get("random_key")
                if not product_id:
                    continue
                product_url = f"https://torob.com/p/{product_id}/"
                if not self._is_valid_product_url(product_url):
                    continue
                price = p.get("price")
                original = p.get("old_price") or p.get("price_before_discount")
                discount = p.get("discount_percent")
                if discount is None and original and price and original > price:
                    discount = round((1 - price / original) * 100)
                if min_discount is not None and (discount or 0) < min_discount:
                    continue
                results.append(DealResult(
                    product_name=p.get("name", "")[:100],
                    store="torob",
                    product_url=product_url,
                    original_price=original,
                    discounted_price=price,
                    discount_percent=discount,
                    availability="موجود",
                ))
        except Exception as e:
            logger.warning(f"Torob offers fetch failed: {e}")
        return results

    async def _search_general_deals_via_tavily(
        self, min_discount: Optional[int] = None, max_results: int = 10
    ) -> List[DealResult]:
        if not self.tavily:
            return []
        results = []
        try:
            discount_text = f"بالای {min_discount} درصد" if min_discount else ""
            query = f"محصولات تخفیف دار بلک فرایدی {discount_text} سایت فروشگاهی ایران"
            res = await asyncio.to_thread(
                self.tavily.search,
                query=query,
                search_depth="advanced",
                max_results=10,
            )
            for item in res.get("results", []):
                url = item.get("url", "")
                if not url or not self._is_valid_product_url(url):
                    continue
                content = item.get("content", "")
                prices = self._extract_prices_from_text(content)
                original, discounted, percent = self._parse_prices(prices)
                if min_discount is not None and (percent or 0) < min_discount:
                    continue
                store = self._extract_store_from_url(url)
                results.append(DealResult(
                    product_name=item.get("title", "")[:100],
                    store=store,
                    product_url=url,
                    original_price=original,
                    discounted_price=discounted,
                    discount_percent=percent,
                ))
        except Exception as e:
            logger.warning(f"General deals Tavily search failed: {e}")
        return results

    async def _search_product_deals(
        self, query: str, min_discount: Optional[int] = None
    ) -> List[DealResult]:
        tasks = [
            self._search_digikala_product(query, min_discount),
            self._search_torob_product(query, min_discount),
            self._search_generic_tavily_product(query, min_discount),
        ]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        merged: List[DealResult] = []
        seen = set()
        for result_list in all_results:
            if isinstance(result_list, Exception):
                continue
            for deal in result_list:
                if deal.product_url not in seen and self._is_valid_product_url(deal.product_url):
                    seen.add(deal.product_url)
                    merged.append(deal)
        merged.sort(key=lambda d: (-(d.discount_percent or 0), d.discounted_price or 10**12))
        return merged

    async def _search_digikala_product(self, query: str, min_discount: Optional[int] = None) -> List[DealResult]:
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
                discount = p.get("discount_percent")
                if discount is None and original and discounted and original > discounted:
                    discount = round((1 - discounted / original) * 100)
                if min_discount is not None and (discount or 0) < min_discount:
                    continue
                results.append(DealResult(
                    product_name=p.get("title_fa") or p.get("title", "")[:100],
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
            logger.warning(f"Digikala product search failed: {e}")
        return results

    async def _search_torob_product(self, query: str, min_discount: Optional[int] = None) -> List[DealResult]:
        results = []
        try:
            url = f"https://api.torob.com/v4/base-product/search/?q={query}&page=0"
            resp = await self._http.get(url)
            if resp.status_code != 200:
                return results
            data = resp.json()
            products = data.get("results", [])
            for p in products[:5]:
                product_id = p.get("id")
                if not product_id:
                    continue
                product_url = f"https://torob.com/p/{product_id}/"
                if not self._is_valid_product_url(product_url):
                    continue
                price = p.get("price")
                original = p.get("old_price")
                discount = None
                if original and price and original > price:
                    discount = round((1 - price / original) * 100)
                if min_discount is not None and (discount or 0) < min_discount:
                    continue
                results.append(DealResult(
                    product_name=p.get("name", "")[:100],
                    store="torob",
                    product_url=product_url,
                    original_price=original,
                    discounted_price=price,
                    discount_percent=discount,
                ))
        except Exception as e:
            logger.warning(f"Torob product search failed: {e}")
        return results

    async def _search_generic_tavily_product(self, query: str, min_discount: Optional[int] = None) -> List[DealResult]:
        if not self.tavily:
            return []
        results = []
        try:
            tavily_query = f"خرید {query} تخفیف بلک فرایدی قیمت"
            res = await asyncio.to_thread(
                self.tavily.search,
                query=tavily_query,
                search_depth="advanced",
                max_results=6,
            )
            for item in res.get("results", []):
                url = item.get("url", "")
                if not url or not self._is_valid_product_url(url):
                    continue
                content = item.get("content", "")
                prices = self._extract_prices_from_text(content)
                original, discounted, percent = self._parse_prices(prices)
                if min_discount is not None and (percent or 0) < min_discount:
                    continue
                store = self._extract_store_from_url(url)
                results.append(DealResult(
                    product_name=item.get("title", "")[:100],
                    store=store,
                    product_url=url,
                    original_price=original,
                    discounted_price=discounted,
                    discount_percent=percent,
                ))
        except Exception as e:
            logger.warning(f"Generic Tavily product search failed: {e}")
        return results

    async def search_deals(
        self, query: str, max_results: int = 10
    ) -> Tuple[List[DealResult], SearchStats]:
        import time
        start_time = time.time()

        min_discount = self._extract_min_discount(query)
        is_general = self._is_general_deal_query(query)

        if is_general:
            tasks = [
                self._fetch_digikala_incredible_offers(min_discount, max_results),
                self._fetch_torob_offers(min_discount, max_results),
                self._search_general_deals_via_tavily(min_discount, max_results),
            ]
        else:
            tasks = [self._search_product_deals(query, min_discount)]

        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        merged: List[DealResult] = []
        seen = set()
        for result_list in all_results:
            if isinstance(result_list, Exception):
                logger.warning(f"Search task exception: {result_list}")
                continue
            for deal in result_list:
                if deal.product_url not in seen and self._is_valid_product_url(deal.product_url):
                    seen.add(deal.product_url)
                    merged.append(deal)

        if min_discount is not None:
            merged = [d for d in merged if (d.discount_percent or 0) >= min_discount]

        merged.sort(key=lambda d: (-(d.discount_percent or 0), d.discounted_price or 10**12))
        merged = merged[:max_results]

        stats = SearchStats(
            total_found=len(merged),
            stores_searched=3,
            stores_with_results=len({d.store for d in merged}),
            best_discount_percent=max((d.discount_percent for d in merged if d.discount_percent), default=None),
            best_price=min((d.discounted_price for d in merged if d.discounted_price), default=None),
            search_duration_seconds=round(time.time() - start_time, 2),
            timestamp=datetime.datetime.now().isoformat(),
        )
        return merged, stats

    def _extract_store_from_url(self, url: str) -> str:
        for store, domain in [
            ("digikala", "digikala.com"), ("torob", "torob.com"),
            ("snappshop", "snappshop.ir"), ("technolife", "technolife.com"),
            ("banimode", "banimode.com"), ("janebi", "janebi.com"),
        ]:
            if domain in url:
                return store
        return url.split("//")[-1].split("/")[0].replace("www.", "").split(".")[0]

    def format_deals(self, deals: List[DealResult], stats: SearchStats, query: str) -> str:
        if not deals:
            return (
                f"🛍️ <b>جستجوی بلک‌فرایدی برای «{query}»</b>\n\n"
                f"⚠️ متأسفانه تخفیف فعالی پیدا نکردم.\n"
                f"📊 {stats.stores_searched} فروشگاه بررسی شد | ⏱ {stats.search_duration_seconds} ثانیه\n\n"
                f"💡 نام دقیق‌تر یا برند محصول را بنویسید، یا درصد تخفیف دلخواه را ذکر کنید (مثلاً «بالای ۹۰ درصد»)."
            )

        header = f"🛍️ <b>نتایج بلک‌فرایدی برای «{query}»</b>\n"
        stats_line = (
            f"📊 <b>آمار:</b> {stats.total_found} محصول از {stats.stores_with_results} فروشگاه | ⏱ {stats.search_duration_seconds} ثانیه\n"
        )
        if stats.best_discount_percent:
            stats_line += f"🏆 <b>بیشترین تخفیف:</b> {stats.best_discount_percent}٪"
            if stats.best_price:
                stats_line += f" | 💰 <b>کمترین قیمت:</b> {stats.best_price:,} تومان"
            stats_line += "\n"

        lines = [header, stats_line, "─" * 30 + "\n"]

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
