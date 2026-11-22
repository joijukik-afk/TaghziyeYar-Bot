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

    async def search(
        self,
        query: str,
        max_per_source: int = 10,
        max_concurrency: int = 4,
    ) -> Tuple[
        List[VerificationResult], SearchStats, Dict[str, Any]
    ]:
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
                    logger.exception(
                        "[%s] search failed", adapter.name
                    )
                    return adapter, exc

        tasks = [run(a) for a in self.adapters]
        results = await asyncio.gather(
            *tasks, return_exceptions=False
        )

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
            v = PriceVerifier(
                cross_seller_median=median
            ).verify(deal)
            verified.append(v)

        stats.verified_deals = sum(
            1 for v in verified if v.real_discount > 0
        )
        ranked = self.ranker.rank(verified)
        report.deals_qualified = sum(
            1 for v in ranked if v.tier in ("S", "A", "B")
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

    @staticmethod
    def _cross_seller_median(
        deal: DealResult, all_deals: List[DealResult]
    ) -> int:
        if not deal.title:
            return 0
        norm_title = deal.title.strip().lower()
        prices = [
            d.price
            for d in all_deals
            if d.price > 0
            and d.title.strip().lower() == norm_title
        ]
        if len(prices) < 3:
            return 0
        return int(statistics.median(prices))

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

        if not deals:
            failed = (
                ", ".join(stats.failed_sources or [])
                or "هیچ منبعی"
            )
            return (
                f"🔍 جستجو برای «{q}»\n\n"
                f"متأسفانه در این دور تخفیف قابل ارائه‌ای "
                f"پیدا نشد.\n\n"
                f"📡 منابع پرسیده‌شده: "
                f"{stats.queried_sources}\n"
                f"⚠️ منابع ناموفق: {failed}\n\n"
                f"💡 راهنمایی: اگر ترب و اسنپ‌شاپ ناموفق‌اند، "
                f"به دلیل محدودیت IP ایران است. دیجی‌کالا "
                f"باید کار کند."
            )

        lines = [f"🛍️ نتایج جستجو برای «{q}»", ""]
        lines.append(
            f"📊 {len(deals)} محصول از "
            f"{stats.queried_sources} فروشگاه"
        )
        lines.append("")

        for i, v in enumerate(deals[:10], 1):
            d = v.deal
            lines.append(f"{i}. {d.title[:80]}")
            if d.price:
                lines.append(f"   ⚡ {d.price:,} تومان")
            if d.old_price and d.old_price > d.price:
                lines.append(f"   ❌ قبلاً: {d.old_price:,} تومان")
            if v.real_discount > 0:
                lines.append(
                    f"   📉 تخفیف: {v.real_discount:.0f}%"
                )
            else:
                lines.append("   📉 تخفیف: قابل تأیید نیست")
            lines.append(f"   🏪 {d.store}")
            lines.append(f"   🔗 {d.product_url}")
            lines.append("")

        if stats.failed_sources:
            lines.append(
                f"⚠️ منابع ناموفق: "
                f"{', '.join(stats.failed_sources)}"
            )

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
