"""سرویس پیشرفته بلک‌فرایدی — جستجوی چندلایه با APIهای رسمی و پوشش ۳۰+ فروشگاه ایرانی."""

import logging
import asyncio
import re
import json
import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

import httpx
from tavily import TavilyClient

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class DealResult:
    """نتیجه یک تخفیف با اطلاعات کامل محصول."""
    product_name: str
    store: str
    product_url: str  # لینک مستقیم صفحه محصول (نه صفحه اصلی)
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
    """آمار واقعی جستجو."""
    total_found: int = 0
    stores_searched: int = 0
    stores_with_results: int = 0
    best_discount_percent: Optional[int] = None
    best_price: Optional[int] = None
    search_duration_seconds: float = 0.0
    timestamp: str = ""


class BlackFridayService:
    """موتور جستجوی پیشرفته تخفیف‌های بلک‌فرایدی با پوشش ۳۰+ فروشگاه ایرانی."""

    # ==================================================================
    #  🏬 دیکشنری جامع فروشگاه‌ها (بر اساس لیست استخراج‌شده)
    # ==================================================================
    STORES = {
        # --- کالای دیجیتال ---
        "digikala": {
            "domain": "digikala.com",
            "api_base": "https://api.digikala.com/v1",
            "search_endpoint": "/search/?q={query}&page=1",
            "product_url_pattern": "https://www.digikala.com/product/dkp-{id}/",
            "category": "digital",
        },
        "technolife": {
            "domain": "technolife.com",
            "api_base": "https://www.technolife.com/graphql",
            "search_endpoint": None,  # GraphQL
            "product_url_pattern": "https://www.technolife.com/product/{slug}/",
            "category": "digital",
        },
        "janebi": {
            "domain": "janebi.com",
            "product_url_pattern": "https://janebi.com/product/{id}",
            "category": "digital",
        },
        "torob": {
            "domain": "torob.com",
            "api_base": "https://api.torob.com/v4",
            "search_endpoint": "/base-product/search/?q={query}&page=0",
            "product_url_pattern": "https://torob.com/p/{id}/",
            "category": "digital",
        },
        "zanbil": {
            "domain": "zanbil.ir",
            "category": "digital",
        },
        "emalls": {
            "domain": "emalls.ir",
            "category": "digital",
        },
        "lipak": {
            "domain": "lipak.com",
            "category": "digital",
        },

        # --- مد و پوشاک ---
        "banimode": {
            "domain": "banimode.com",
            "api_base": "https://mobapi.banimode.com/api/v2",
            "search_endpoint": "/products/search?q={query}",
            "product_url_pattern": "https://banimode.com/product/{id}/",
            "category": "fashion",
        },
        "digistyle": {
            "domain": "digistyle.com",
            "category": "fashion",
        },
        "modiseh": {
            "domain": "modiseh.com",
            "category": "fashion",
        },
        "shixon": {
            "domain": "shixon.com",
            "category": "fashion",
        },
        "charmmashhad": {
            "domain": "charmmashhad.com",
            "category": "fashion",
        },
        "novinleather": {
            "domain": "novinleather.com",
            "category": "fashion",
        },
        "pooshakland": {
            "domain": "pooshakland.com",
            "category": "fashion",
        },
        "isocollection": {
            "domain": "isocollection.ir",
            "category": "fashion",
        },

        # --- زیبایی و آرایشی ---
        "khanoumi": {
            "domain": "khanoumi.com",
            "category": "beauty",
        },
        "atrafshan": {
            "domain": "atrafshan.ir",
            "category": "beauty",
        },
        "beautykala": {
            "domain": "beautykala.com",
            "category": "beauty",
        },

        # --- خانه و آشپزخانه ---
        "xbat": {
            "domain": "xbat.ir",
            "category": "home",
        },
        "avatgallery": {
            "domain": "avatgallery.com",
            "category": "home",
        },
        "kalabord": {
            "domain": "kalabord.com",
            "category": "home",
        },

        # --- مارکت‌پلیس عمومی ---
        "basalam": {
            "domain": "basalam.com",
            "category": "general",
        },
        "divar": {
            "domain": "divar.ir",
            "category": "general",
        },
        "sheypoor": {
            "domain": "sheypoor.com",
            "category": "general",
        },
        "esam": {
            "domain": "esam.ir",
            "category": "general",
        },
        "residkala": {
            "domain": "residkala.com",
            "category": "general",
        },

        # --- سوپرمارکت آنلاین ---
        "snappshop": {
            "domain": "snappshop.ir",
            "api_base": "https://apix.snappshop.ir",
            "search_endpoint": "/products/v2/search?q={query}",
            "product_url_pattern": "https://snappshop.ir/product/{id}/",
            "category": "grocery",
        },
        "okala": {
            "domain": "okala.com",
            "category": "grocery",
        },
        "tapsishop": {
            "domain": "tapsishop.com",
            "category": "grocery",
        },

        # --- ورزش و سرگرمی ---
        "aryoshop": {
            "domain": "aryoshop.com",
            "category": "sport",
        },
    }

    CATEGORY_KEYWORDS = {
        "digital": ["موبایل", "گوشی", "iphone", "آیفون", "سامسونگ", "شیائومی", "لپ‌تاپ", "لپ تاپ", "مک‌بوک", "هدفون", "هندزفری", "پاوربانک", "شارژر"],
        "fashion": ["لباس", "پوشاک", "تیشرت", "شلوار", "کفش", "کیف", "مانتو", "شلوارک", "پیراهن", "اکسسوری", "چرم"],
        "beauty": ["آرایشی", "بهداشتی", "کرم", "عطر", "ادکلن", "سرم", "شامپو", "لوازم آرایشی"],
        "home": ["خانه", "آشپزخانه", "لوازم خانگی", "یخچال", "ماشین لباسشویی", "مبلمان", "مبل", "فرش"],
        "grocery": ["سوپرمارکت", "مواد غذایی", "خوراکی", "میوه", "لبنیات"],
        "general": [],
    }

    def __init__(self):
        settings = get_settings()
        self.tavily_key = settings.tavily_api_key
        self.tavily = TavilyClient(api_key=self.tavily_key) if self.tavily_key else None
        self._http = httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TaghziyeYarBot/1.0)"},
        )

    async def close(self):
        await self._http.aclose()

    # ==================================================================
    #  🔍 لایه ۱: APIهای رسمی (سریع‌ترین و دقیق‌ترین)
    # ==================================================================
    async def _search_digikala(self, query: str) -> List[DealResult]:
        """جستجوی مستقیم در دیجی‌کالا با API."""
        results = []
        try:
            url = f"https://api.digikala.com/v1/search/?q={query}&page=1"
            resp = await self._http.get(url)
            if resp.status_code != 200:
                return results

            data = resp.json()
            products = data.get("data", {}).get("products", [])

            for p in products[:6]:
                product_id = p.get("id")
                if not product_id:
                    continue

                product_url = f"https://www.digikala.com/product/dkp-{product_id}/"
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

    async def _search_torob(self, query: str) -> List[DealResult]:
        """جستجوی مستقیم در ترب (مقایسه‌گر قیمت)."""
        results = []
        try:
            url = f"https://api.torob.com/v4/base-product/search/?q={query}&page=0"
            resp = await self._http.get(url)
            if resp.status_code != 200:
                return results

            data = resp.json()
            products = data.get("results", [])

            for p in products[:6]:
                product_id = p.get("id")
                if not product_id:
                    continue

                product_url = f"https://torob.com/p/{product_id}/"
                price = p.get("price")
                original = p.get("old_price")
                discount = None
                if original and price and original > price:
                    discount = round((1 - price / original) * 100)

                results.append(DealResult(
                    product_name=p.get("name", query)[:100],
                    store="torob",
                    product_url=product_url,
                    original_price=original,
                    discounted_price=price,
                    discount_percent=discount,
                    seller="مقایسه‌گر قیمت",
                    availability="موجود" if p.get("availability") else "ناموجود",
                ))
        except Exception as e:
            logger.warning(f"Torob API search failed: {e}")
        return results

    async def _search_snappshop(self, query: str) -> List[DealResult]:
        """جستجوی مستقیم در اسنپ‌شاپ با API."""
        results = []
        try:
            url = f"https://apix.snappshop.ir/products/v2/search?q={query}"
            resp = await self._http.get(url)
            if resp.status_code != 200:
                return results

            data = resp.json()
            products = data.get("data", {}).get("products", []) or data.get("products", [])

            for p in products[:6]:
                product_id = p.get("id")
                if not product_id:
                    continue

                product_url = f"https://snappshop.ir/product/{product_id}/"
                price = p.get("price")
                original = p.get("old_price")
                discount = None
                if original and price and original > price:
                    discount = round((1 - price / original) * 100)

                results.append(DealResult(
                    product_name=p.get("name", query)[:100],
                    store="snappshop",
                    product_url=product_url,
                    original_price=original,
                    discounted_price=price,
                    discount_percent=discount,
                    seller=p.get("seller", {}).get("name"),
                    availability="موجود" if p.get("in_stock") else "ناموجود",
                ))
        except Exception as e:
            logger.warning(f"SnappShop API search failed: {e}")
        return results

    async def _search_banimode(self, query: str) -> List[DealResult]:
        """جستجوی مستقیم در بانی‌مد با API."""
        results = []
        try:
            url = f"https://mobapi.banimode.com/api/v2/products/search?q={query}"
            resp = await self._http.get(url)
            if resp.status_code != 200:
                return results

            data = resp.json()
            products = data.get("data", []) or data.get("products", [])

            for p in products[:6]:
                product_id = p.get("id")
                if not product_id:
                    continue

                product_url = f"https://banimode.com/product/{product_id}/"
                price = p.get("price")
                original = p.get("old_price")
                discount = None
                if original and price and original > price:
                    discount = round((1 - price / original) * 100)

                results.append(DealResult(
                    product_name=p.get("name", query)[:100],
                    store="banimode",
                    product_url=product_url,
                    original_price=original,
                    discounted_price=price,
                    discount_percent=discount,
                    availability="موجود" if p.get("stock", 0) > 0 else "ناموجود",
                ))
        except Exception as e:
            logger.warning(f"Banimode API search failed: {e}")
        return results

    # ==================================================================
    #  🔍 لایه ۲: Tavily Extract برای فروشگاه‌های بدون API
    # ==================================================================
    async def _search_with_tavily_extract(
        self, query: str, domain: str, store_key: str
    ) -> List[DealResult]:
        """جستجوی Tavily + Extract برای یافتن صفحه محصول و استخراج قیمت."""
        if not self.tavily:
            return []

        results = []
        try:
            tavily_query = f"site:{domain} {query} قیمت تخفیف"
            res = await asyncio.to_thread(
                self.tavily.search,
                query=tavily_query,
                search_depth="advanced",
                max_results=5,
            )

            urls = [r.get("url", "") for r in res.get("results", []) if r.get("url")]
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

    # ==================================================================
    #  🔍 لایه ۳: جستجوی عمومی Tavily (برای فروشگاه‌های ناشناخته)
    # ==================================================================
    async def _search_generic_tavily(self, query: str) -> List[DealResult]:
        """جستجوی عمومی برای یافتن تخفیف در فروشگاه‌های مختلف."""
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

                if not self._looks_like_product_page(url):
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

    # ==================================================================
    #  🧠 متد اصلی جستجو (چندلایه و موازی)
    # ==================================================================
    async def search_deals(
        self, query: str, max_results_per_store: int = 3
    ) -> Tuple[List[DealResult], SearchStats]:
        """جستجوی جامع تخفیف‌های بلک‌فرایدی در همه فروشگاه‌ها."""
        import time
        start_time = time.time()

        category = self._detect_category(query)
        tasks = []

        # لایه ۱: APIهای رسمی
        tasks.append(self._search_digikala(query))
        tasks.append(self._search_torob(query))
        tasks.append(self._search_snappshop(query))
        tasks.append(self._search_banimode(query))

        # لایه ۲: Tavily Extract برای بقیه فروشگاه‌های شناخته‌شده
        api_stores = {"digikala", "torob", "snappshop", "banimode"}
        for store_key, store_config in self.STORES.items():
            if store_key in api_stores:
                continue
            if store_config.get("domain"):
                tasks.append(
                    self._search_with_tavily_extract(
                        query, store_config["domain"], store_key
                    )
                )

        # لایه ۳: جستجوی عمومی برای فروشگاه‌های ناشناخته
        tasks.append(self._search_generic_tavily(query))

        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: List[DealResult] = []
        seen_urls = set()

        for result_list in all_results:
            if isinstance(result_list, Exception):
                continue
            for deal in result_list:
                if deal.product_url not in seen_urls:
                    seen_urls.add(deal.product_url)
                    merged.append(deal)

        merged.sort(
            key=lambda d: (
                -(d.discount_percent or 0),
                d.discounted_price or 10**12,
            )
        )

        merged = merged[: max_results_per_store * 6]

        stats = SearchStats(
            total_found=len(merged),
            stores_searched=len(self.STORES) + 1,
            stores_with_results=len({d.store for d in merged}),
            best_discount_percent=max(
                (d.discount_percent for d in merged if d.discount_percent), default=None
            ),
            best_price=min(
                (d.discounted_price for d in merged if d.discounted_price), default=None
            ),
            search_duration_seconds=round(time.time() - start_time, 2),
            timestamp=datetime.datetime.now().isoformat(),
        )

        return merged, stats

    # ==================================================================
    #  🧠 ابزارهای کمکی
    # ==================================================================
    def _detect_category(self, query: str) -> Optional[str]:
        q = query.lower()
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            if any(kw in q for kw in keywords):
                return category
        return None

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

    def _looks_like_product_page(self, url: str) -> bool:
        patterns = [r"/product/", r"/p/", r"/dp/", r"/dkp-", r"/item/", r"/goods/", r"/shop/", r"/pr/"]
        return any(re.search(p, url.lower()) for p in patterns)

    def _extract_store_from_url(self, url: str) -> str:
        for store_key, store_config in self.STORES.items():
            if store_config.get("domain") and store_config["domain"] in url:
                return store_key
        return url.split("//")[-1].split("/")[0].replace("www.", "").split(".")[0]

    # ==================================================================
    #  📝 قالب‌بندی خروجی
    # ==================================================================
    def format_deals(self, deals: List[DealResult], stats: SearchStats, query: str) -> str:
        if not deals:
            return (
                f"🛍️ <b>جستجوی بلک‌فرایدی برای «{query}»</b>\n\n"
                f"⚠️ متأسفانه تخفیف فعالی پیدا نکردم.\n"
                f"📊 آمار جستجو: {stats.stores_searched} فروشگاه بررسی شد، "
                f"هیچ نتیجه‌ای یافت نشد.\n\n"
                f"💡 <i>پیشنهاد: نام محصول را دقیق‌تر وارد کنید یا نام فروشگاه را مشخص کنید.</i>"
            )

        lines = [f"🛍️ <b>بهترین تخفیف‌های بلک‌فرایدی برای «{query}»</b>\n"]

        lines.append(
            f"📊 <b>آمار جستجو:</b> {stats.total_found} محصول از "
            f"{stats.stores_with_results} فروشگاه | "
            f"⏱ {stats.search_duration_seconds} ثانیه\n"
        )

        if stats.best_discount_percent:
            lines.append(
                f"🏆 <b>بهترین تخفیف:</b> {stats.best_discount_percent}٪ | "
                f"💰 <b>کمترین قیمت:</b> {stats.best_price:,} تومان\n"
            )

        lines.append("─" * 30 + "\n")

        for i, deal in enumerate(deals[:8], 1):
            price_line = ""
            if deal.discounted_price and deal.original_price:
                price_line = (
                    f"  💰 {deal.discounted_price:,} تومان "
                    f"(<s>{deal.original_price:,}</s>) — "
                    f"<b>{deal.discount_percent}٪ تخفیف</b>\n"
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
                extra += f"  🏪 فروشنده: {deal.seller}\n"
            if deal.availability:
                extra += f"  📦 {deal.availability}\n"

            lines.append(
                f"{i}. <b>{deal.product_name}</b>\n"
                f"  🏬 {deal.store}\n"
                f"{price_line}"
                f"{extra}"
                f"  🔗 <a href='{deal.product_url}'>مشاهده و خرید</a>\n"
            )

        if len(deals) > 8:
            lines.append(f"\n➕ {len(deals) - 8} نتیجه دیگر...")

        lines.append(
            f"\n📅 <i>بلک‌فرایدی ۱۴۰۵: جمعه ۶ آذر (۲۷ نوامبر ۲۰۲۶) — حراج‌ها از ۱ آذر</i>"
        )

        return "\n".join(lines)


_black_friday_service: Optional[BlackFridayService] = None


def get_black_friday_service() -> BlackFridayService:
    global _black_friday_service
    if _black_friday_service is None:
        _black_friday_service = BlackFridayService()
    return _black_friday_service
