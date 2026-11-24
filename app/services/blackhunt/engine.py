"""Orchestrates discovery → verification → ranking."""
from __future__ import annotations

import asyncio
import logging
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.services.blackhunt.adapters import (
    BaseAdapter,
    build_adapters,
)
from app.services.blackhunt.analyzer import (
    DealRanker,
    PriceVerifier,
    VerificationResult,
)
from app.services.blackhunt.models import DealResult, HuntReport

logger = logging.getLogger(__name__)


@dataclass
class SearchStats:
    queried_sources: int = 0
    total_deals: int = 0
    verified_deals: int = 0
    failed_sources: List[str] = None
    hunt_report: Optional[HuntReport] = None

    def __post_init__(self) -> None:
        if self.failed_sources is None:
            self.failed_sources = []


class HuntEngine:
    def __init__(
        self, adapters: Optional[List[BaseAdapter]] = None,
    ) -> None:
        self.adapters: List[BaseAdapter] = adapters or build_adapters()
        self.ranker = DealRanker()

    # ------------------------------------------------------------------
    # API قدیمی (AutoHunter و persona — دست نخورده)
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        max_per_source: int = 10,
        max_concurrency: int = 4,
    ) -> Tuple[List[VerificationResult], SearchStats, Dict[str, Any]]:
        stats = SearchStats()
        report = HuntReport()
        sem = asyncio.Semaphore(max_concurrency)

        async def run(adapter: BaseAdapter):
            async with sem:
                try:
                    return adapter, await adapter.search(
                        query, max_results=max_per_source
                    )
                except Exception as exc:
                    logger.exception("[%s] search failed", adapter.name)
                    return adapter, exc

        tasks = [run(a) for a in self.adapters]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        all_deals: List[DealResult] = []
        for adapter, res in results:
            if isinstance(res, Exception):
                stats.failed_sources.append(adapter.name)
                report.errors.append(f"{adapter.name}: {res}")
                continue
            stats.queried_sources += 1
            stats.total_deals += len(res)
            all_deals.extend(res)

        report.deals_found = len(all_deals)

        verified: List[VerificationResult] = []
        for deal in all_deals:
            median = self._cross_seller_median(deal, all_deals)
            v = PriceVerifier(cross_seller_median=median).verify(deal)
            verified.append(v)

        stats.verified_deals = sum(
            1 for v in verified if v.real_discount > 0
        )
        ranked = self.ranker.rank(verified)
        report.deals_qualified = sum(
            1 for v in ranked if v.tier in ("S", "A", "B", "C")
        )
        report.finish()
        stats.hunt_report = report

        logger.info(
            "HuntEngine: query='%s' sources=%d deals=%d "
            "verified=%d failed=%s",
            query,
            stats.queried_sources,
            stats.total_deals,
            stats.verified_deals,
            stats.failed_sources or "none",
        )

        intent_dict: Dict[str, Any] = {
            "query": query,
            "original_request": query,
        }
        return ranked, stats, intent_dict

    # ------------------------------------------------------------------
    # API جدید (wizard — با فیلتر کامل)
    # ------------------------------------------------------------------
    async def search_advanced(self, sq) -> List[VerificationResult]:
        """جستجو با فیلتر کامل بر اساس SearchQuery (برای wizard)."""
        adapters = [
            a for a in self.adapters
            if getattr(a, "name", "") in sq.stores
        ] or self.adapters

        async def _safe(adapter):
            try:
                return await adapter.search(
                    sq.text, max_results=sq.max_results
                )
            except Exception as exc:
                logger.warning(
                    "[%s] advanced search failed: %s",
                    adapter.name, exc,
                )
                return []

        results = await asyncio.gather(*[_safe(a) for a in adapters])
        all_deals: List[DealResult] = []
        for chunk in results:
            all_deals.extend(chunk or [])

        # Dedup (store + normalized title)
        seen = set()
        unique: List[DealResult] = []
        for d in all_deals:
            fp = (
                getattr(d, "store", "") or "",
                (getattr(d, "title", "") or "").strip().lower(),
            )
            if fp in seen:
                continue
            seen.add(fp)
            unique.append(d)

        # Verify
        verified: List[VerificationResult] = []
        for deal in unique:
            median = self._cross_seller_median(deal, unique)
            v = PriceVerifier(cross_seller_median=median).verify(deal)
            verified.append(v)

        # Filter
        filtered: List[VerificationResult] = []
        for v in verified:
            if v.tier == "UNVERIFIED":
                if sq.show_unverified:
                    filtered.append(v)
                continue
            if v.real_discount < sq.min_discount:
                continue
            filtered.append(v)

        # Sort
        if sq.sort == "best_discount":
            filtered.sort(key=lambda v: -v.real_discount)
        elif sq.sort == "cheapest":
            filtered.sort(
                key=lambda v: v.deal.price or float("inf")
            )
        elif sq.sort == "newest":
            pass
        else:  # smart
            tier_weight = {"S": 4, "A": 3, "B": 2, "C": 1}
            filtered.sort(
                key=lambda v: -(
                    v.real_discount * 0.7
                    + tier_weight.get(v.tier, 0) * 10
                )
            )

        logger.info(
            "HuntEngine.advanced: query='%s' stores=%s "
            "unique=%d qualified=%d min_disc=%s show_unv=%s",
            sq.text, sq.stores, len(unique),
            len(filtered), sq.min_discount, sq.show_unverified,
        )
        return filtered[: sq.max_results]

    @staticmethod
    def _cross_seller_median(
        deal: DealResult, all_deals: List[DealResult]
    ) -> int:
        if not deal.title:
            return 0
        key = deal.title.strip().lower()
        prices = [
            d.price
            for d in all_deals
            if d.price > 0
            and d.title.strip().lower() == key
        ]
        if len(prices) < 2:
            return 0
        return int(statistics.median(prices))

    # ------------------------------------------------------------------
    # فرمت گزارش — فیکس اصلی
    # ------------------------------------------------------------------
    async def format_report(self, deals, stats, intent) -> str:
        q = ""
        if isinstance(intent, dict):
            q = intent.get("query", "") or intent.get(
                "original_request", ""
            )
        elif isinstance(intent, str):
            q = intent
        elif hasattr(intent, "query"):
            q = getattr(intent, "query", "") or ""
        elif hasattr(intent, "original_request"):
            q = getattr(intent, "original_request", "") or ""

        # ✅ فقط تخفیف‌های تأییدشده نمایش داده می‌شن
        qualified = [
            v for v in deals
            if v.tier in ("S", "A", "B", "C")
        ]
        qualified.sort(key=lambda v: -v.real_discount)

        if not qualified:
            failed = (
                ", ".join(stats.failed_sources or [])
                or "هیچ منبعی"
            )
            return (
                f"🔍 جستجو برای «{q}»\n\n"
                f"❌ متأسفانه در این دور هیچ تخفیف "
                f"واقعی و قابل‌تأییدی پیدا نشد.\n\n"
                f"📊 آمار:\n"
                f"• منابع موفق: {stats.queried_sources}\n"
                f"• منابع ناموفق: {failed}\n"
                f"• محصولات بررسی‌شده: {stats.total_deals}\n"
                f"• تخفیف قابل‌تأیید: 0\n\n"
                f"💡 چه کنم؟\n"
                f"• از /advsearch استفاده کن و "
                f"فیلترها رو دقیق‌تر تنظیم کن\n"
                f"• یا عبارت دقیق‌تری بنویس "
                f"(مثلاً «گوشی سامسونگ A55 256»)\n"
                f"• یا چند دقیقه دیگه دوباره امتحان کن\n\n"
                f"ℹ️ چرا؟ فروشگاه‌هایی مثل ترب و اسنپ‌شاپ "
                f"معمولاً «قیمت قبلی» برنمی‌گردونن. "
                f"به همین خاطر تخفیفشون قابل تأیید نیست."
            )

        lines = [f"🛍️ نتایج جستجو برای «{q}»", ""]
        lines.append(
            f"📊 {len(qualified)} تخفیف تأییدشده از "
            f"{stats.queried_sources} فروشگاه | "
            f"{stats.total_deals} محصول بررسی شد"
        )
        lines.append("")

        for i, v in enumerate(qualified[:10], 1):
            d = v.deal
            lines.append(f"{i}. {d.title[:80]}")
            if d.price:
                lines.append(f"   ⚡ {d.price:,} تومان")
            if d.old_price and d.old_price > d.price:
                lines.append(
                    f"   ❌ قبلاً: {d.old_price:,} تومان"
                )
            lines.append(
                f"   📉 تخفیف: {v.real_discount:.0f}% "
                f"(اعتبار: {v.tier})"
            )
            lines.append(f"   🏪 {d.store}")
            lines.append(f"   🔗 {d.product_url}")
            lines.append("")

        if stats.failed_sources:
            lines.append(
                f"⚠️ منابع ناموفق: "
                f"{', '.join(stats.failed_sources)}"
            )

        lines.append("")
        lines.append("🔎 برای جستجوی دقیق‌تر: /advsearch")
        return "\n".join(lines)


_engine: Optional[HuntEngine] = None


def get_engine() -> HuntEngine:
    global _engine
    if _engine is None:
        _engine = HuntEngine()
        logger.info(
            "HuntEngine initialized with %d adapters",
            len(_engine.adapters),
        )
    return _engine
