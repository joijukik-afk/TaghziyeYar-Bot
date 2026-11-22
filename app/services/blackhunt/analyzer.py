"""Price verification, ranking and Persian message formatting."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.services.blackhunt.models import DealResult, SearchIntent
from app.services.blackhunt.price_utils import (
    format_price,
    pct_discount,
)

logger = logging.getLogger(__name__)

TIER_S = "S"
TIER_A = "A"
TIER_B = "B"
TIER_C = "C"
TIER_UNVERIFIED = "UNVERIFIED"


@dataclass
class VerificationResult:
    deal: DealResult
    market_median: int
    real_discount: float
    savings: int
    tier: str
    confidence: str
    reason: str


class PriceVerifier:
    def __init__(
        self, cross_seller_median: Optional[int] = None
    ) -> None:
        self.cross_seller_median = cross_seller_median or 0

    def verify(self, deal: DealResult) -> VerificationResult:
        listed = deal.old_price or 0
        current = deal.price or 0
        adv_pct = (
            pct_discount(listed, current)
            if listed > current > 0
            else 0.0
        )
        median = self.cross_seller_median or 0
        real_pct = 0.0
        if median > 0 and current > 0 and median > current:
            real_pct = pct_discount(median, current)
            savings = median - current
        elif listed > current > 0:
            if adv_pct > 95:
                real_pct = 0.0
                savings = 0
            else:
                real_pct = adv_pct
                savings = listed - current
        else:
            savings = 0
        confidence, tier, reason = self._classify(
            real_pct, median, current, listed
        )
        return VerificationResult(
            deal=deal,
            market_median=median,
            real_discount=real_pct,
            savings=savings,
            tier=tier,
            confidence=confidence,
            reason=reason,
        )

    def _classify(self, real_pct, median, current, listed):
        if real_pct <= 0:
            return (
                "UNVERIFIED",
                TIER_UNVERIFIED,
                "تخفیف قابل تأیید نیست",
            )
        if median > 0:
            if real_pct >= 40:
                return (
                    "HIGH",
                    TIER_S,
                    "تخفیف تأییدشده بر مبنای میانهٔ بازار",
                )
            if real_pct >= 20:
                return (
                    "HIGH",
                    TIER_A,
                    "تخفیف خوب نسبت به میانهٔ بازار",
                )
            if real_pct >= 10:
                return (
                    "MEDIUM",
                    TIER_B,
                    "تخفیف متوسط نسبت به میانهٔ بازار",
                )
            return ("LOW", TIER_C, "اختلاف جزئی با بازار")
        if listed > current > 0 and real_pct < 90:
            if real_pct >= 40:
                return (
                    "MEDIUM",
                    TIER_A,
                    "تخفیف بر اساس قیمت قبلی فروشگاه",
                )
            if real_pct >= 15:
                return (
                    "LOW",
                    TIER_B,
                    "تخفیف متوسط (تک‌منبعی)",
                )
            return ("LOW", TIER_C, "تخفیف کوچک (تک‌منبعی)")
        return ("UNVERIFIED", TIER_UNVERIFIED, "شواهد ناکافی")


class DealRanker:
    TIER_ORDER = {
        TIER_S: 4,
        TIER_A: 3,
        TIER_B: 2,
        TIER_C: 1,
        TIER_UNVERIFIED: 0,
    }

    def rank(
        self, results: List[VerificationResult]
    ) -> List[VerificationResult]:
        return sorted(
            results,
            key=lambda r: (
                self.TIER_ORDER.get(r.tier, 0),
                r.real_discount,
                r.savings,
            ),
            reverse=True,
        )


def _esc(text: str) -> str:
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def format_deal_message(v: VerificationResult) -> str:
    d = v.deal
    lines = [
        "🔥 <b>شکار تخفیف واقعی!</b>",
        "",
        f"🎯 <b>{_esc(d.title) or 'محصول'}</b>",
        "",
    ]
    if d.old_price:
        lines.append(
            f"💰 قیمت قبلی: "
            f"<s>{format_price(d.old_price)}</s> تومان"
        )
    lines.append(
        f"⚡ قیمت فعلی: "
        f"<b>{format_price(d.price)}</b> تومان"
    )
    lines.append(
        f"📉 تخفیف واقعی: <b>{v.real_discount:.0f}%</b>"
    )
    if v.savings:
        lines.append(
            f"💎 میزان صرفه‌جویی: "
            f"{format_price(v.savings)} تومان"
        )
    lines.append("")
    lines.append(f"🏪 فروشگاه: {_esc(d.store)}")
    lines.append(
        f"📊 اعتبار تخفیف: {_esc(v.tier)} ({_esc(v.confidence)})"
    )
    lines.append(
        f"🕒 آخرین بررسی: "
        f"{d.fetched_at.strftime('%Y-%m-%d %H:%M')}"
    )
    lines.append("")
    lines.append("🛒 لینک مستقیم خرید:")
    lines.append(
        f'<a href="{d.product_url}">مشاهده در {_esc(d.store)}</a>'
    )
    lines.append("")
    lines.append("⚠️ قیمت و موجودی ممکن است تغییر کند.")
    lines.append("")
    lines.append("#بلک_فرایدی #تخفیف_واقعی #شکار_تخفیف")
    return "\n".join(lines)


# ---- Backward compatibility helpers ----
def analyze_deals(deals: List[DealResult]) -> List[DealResult]:
    return deals


def deduplicate(deals: List[DealResult]) -> List[DealResult]:
    seen = set()
    out = []
    for d in deals:
        if d.product_url in seen:
            continue
        seen.add(d.product_url)
        out.append(d)
    return out


def filter_by_intent(
    deals: List[DealResult], intent: SearchIntent,
) -> List[DealResult]:
    out = []
    for d in deals:
        if intent.min_discount:
            pct = (
                d.real_discount_percent
                or d.listed_discount_percent
                or 0
            )
            if pct < intent.min_discount:
                continue
        out.append(d)
    return out
