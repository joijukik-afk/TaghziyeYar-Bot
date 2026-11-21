"""BlackHunt search engine.

Orchestrates:
    - MCP adapters (Digikala / Torob / SnappShop)
    - Optional AI intent detection
    - Ranking + HTML report generation

Used by main.py's BLACK FRIDAY persona:

    engine = get_engine()
    deals, stats, intent = await engine.search(user_request)
    report = await engine.format_report(deals, stats, intent)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings
from app.services.blackhunt.adapters import search_all_adapters
from app.services.blackhunt.models import DealResult

logger = logging.getLogger(__name__)


class BlackHuntEngine:
    """High-level engine for interactive product search."""

    def __init__(self) -> None:
        self._intent_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self, query: str
    ) -> Tuple[List[DealResult], Dict[str, Any], Dict[str, Any]]:
        """Search every enabled store and return (deals, stats, intent)."""
        settings = get_settings()
        query = (query or "").strip()

        if not query:
            return [], {"found": 0, "stores": []}, {"query": ""}

        # 1. Detect intent (best-effort, non-blocking)
        intent = await self._detect_intent(query)

        # 2. Search all adapters in parallel
        try:
            deals = await search_all_adapters(
                query, settings.auto_hunter_max_results_per_store
            )
        except Exception as exc:
            logger.exception("BlackHunt search failed: %s", exc)
            deals = []

        # 3. Rank & finalise
        deals = self._rank(deals, intent)

        stats: Dict[str, Any] = {
            "found": len(deals),
            "stores": sorted({d.store for d in deals if d.store}),
            "total_stores_searched": len(settings.enabled_mcp_stores),
            "min_discount": settings.auto_hunter_min_discount,
        }
        return deals, stats, intent

    async def format_report(
        self,
        deals: List[DealResult],
        stats: Dict[str, Any],
        intent: Dict[str, Any],
    ) -> str:
        """Render the search result as a Telegram-friendly HTML message."""
        q = (intent or {}).get("query", "")
        if not deals:
            return (
                f"🛍️ <b>جستجو برای «{_esc(q)}»</b>\n\n"
                "متأسفانه در حال حاضر تخفیف قابل ارائه‌ای پیدا نشد.\n\n"
                "💡 ممکن است سرورهای فروشگاه‌ها موقتاً در دسترس نباشند. "
                "چند دقیقه بعد دوباره امتحان کنید."
            )

        lines: List[str] = [
            f"🛍️ <b>نتایج جستجو برای «{_esc(q)}»</b>",
            f"📊 {len(deals)} محصول از "
            f"{len(stats.get('stores', []))} فروشگاه",
            "",
        ]

        for i, deal in enumerate(deals[:10], 1):
            title = _esc((deal.title or "بدون عنوان")[:90])
            lines.append(f"{i}. <b>{title}</b>")

            if deal.price:
                lines.append(f"   💵 {deal.price:,} تومان")
            if deal.old_price and deal.old_price > deal.price:
                lines.append(f"   ❌ قبلاً: {deal.old_price:,} تومان")
            if deal.discount:
                lines.append(f"   🔥 تخفیف: {deal.discount:.0f}%")
            if deal.product_url:
                store = _esc(deal.store or "فروشگاه")
                lines.append(
                    f'   🔗 <a href="{_esc(deal.product_url)}">'
                    f"مشاهده در {store}</a>"
                )
            lines.append("")

        if len(deals) > 10:
            lines.append(f"… و {len(deals) - 10} نتیجه دیگر")

        return "\n".join(lines).strip()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _detect_intent(self, query: str) -> Dict[str, Any]:
        """Extract structured intent from the user's Persian query.

        Fails silently: on any error, only the raw query is returned.
        """
        if query in self._intent_cache:
            return dict(self._intent_cache[query])

        intent: Dict[str, Any] = {"query": query, "category": None, "budget": None}

        try:
            # Lazy import: AI service may not be available in tests
            from app.services.ai_service import get_ai_service

            ai = get_ai_service()
            prompt = (
                "Extract shopping intent from the following Persian query. "
                "Reply ONLY with valid JSON, no markdown, no explanation:\n"
                '{"category": "mobile|laptop|tv|food|clothes|..." '
                'or null, "budget": integer_toman or null}\n\n'
                f"Query: {query}"
            )
            reply, _status = await ai.ask(
                user_message=prompt,
                user_name="system",
                user_id=0,
                custom_system_prompt=(
                    "You are a JSON extractor. Output ONLY JSON."
                ),
                chat_history=[],
            )
            text = (reply or "").strip()
            # Strip possible code fences
            if text.startswith("```"):
                text = text.strip("`").split("\n", 1)[-1]
            data = json.loads(text)
            if isinstance(data, dict):
                intent["category"] = data.get("category")
                intent["budget"] = data.get("budget")
        except Exception as exc:
            logger.debug("Intent detection skipped: %s", exc)

        self._intent_cache[query] = dict(intent)
        return intent

    def _rank(
        self, deals: List[DealResult], intent: Dict[str, Any]
    ) -> List[DealResult]:
        """Sort by discount desc; drop duplicates by URL."""
        seen: set[str] = set()
        valid: List[DealResult] = []
        for deal in deals:
            if not deal.product_url or deal.product_url in seen:
                continue
            seen.add(deal.product_url)
            valid.append(deal)
        valid.sort(key=lambda d: d.discount, reverse=True)
        return valid


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_singleton: Optional[BlackHuntEngine] = None


def get_engine() -> BlackHuntEngine:
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = BlackHuntEngine()
    return _engine_singleton


def _esc(text: Any) -> str:
    """HTML-escape for Telegram parse_mode=HTML."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


__all__ = ["BlackHuntEngine", "get_engine"]
