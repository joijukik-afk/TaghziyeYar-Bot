"""BlackHunt / AutoHunter package public API.

Re-exports everything so callers can simply write:

    from app.services.blackhunt import (
        get_engine, get_auto_hunter, DealResult, search_all_adapters,
    )

If engine.py is not present (or fails to import), a safe in-package
fallback engine is provided so nothing blows up at import time.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# --- Models ---
from app.services.blackhunt.models import DealResult, HuntReport  # noqa: E402

# --- Adapters ---
from app.services.blackhunt.adapters import (  # noqa: E402
    MCPAdapter,
    TavilyAdapter,
    build_adapters,
    close_adapters,
    extract_prices,
    is_valid_product_url,
    normalize_numbers,
    search_all_adapters,
    store_from_url,
)

# --- AutoHunter ---
from app.services.blackhunt.auto_hunter import (  # noqa: E402
    AutoHunter,
    format_deal,
    get_auto_hunter,
    start_auto_hunter,
)

# --- Engine (with safe fallback) ---
try:
    from app.services.blackhunt.engine import get_engine, BlackHuntEngine  # noqa: E402,F401
except Exception as _exc:  # pragma: no cover
    logger.warning(
        "blackhunt.engine could not be imported (%s). "
        "Falling back to a lightweight engine.", _exc,
    )

    class BlackHuntEngine:  # type: ignore[no-redef]
        """Minimal engine so callers don't crash if engine.py is missing."""

        async def search(self, query: str):
            deals = await search_all_adapters(query)
            stats = {"found": len(deals), "stores": list({d.store for d in deals})}
            intent = {"query": query}
            return deals, stats, intent

        async def format_report(self, deals, stats, intent) -> str:
            if not deals:
                q = (intent or {}).get("query", "")
                return f"🛍️ برای «{q}» تخفیف قابل ارائه‌ای پیدا نشد."
            lines = ["🛍️ <b>نتایج جستجو</b>", ""]
            for deal in deals[:10]:
                lines.append(f"• <b>{deal.title[:80]}</b>")
                lines.append(f"  🔥 {deal.discount:.0f}% | 💵 {deal.price:,} تومان"
                             if deal.price else f"  🔥 {deal.discount:.0f}%")
                lines.append(f'  🔗 <a href="{deal.product_url}">{deal.store}</a>')
                lines.append("")
            return "\n".join(lines)

    _fallback_engine: "BlackHuntEngine | None" = None

    def get_engine():  # type: ignore[no-redef]
        global _fallback_engine
        if _fallback_engine is None:
            _fallback_engine = BlackHuntEngine()
        return _fallback_engine


__all__ = [
    # models
    "DealResult",
    "HuntReport",
    # adapters
    "MCPAdapter",
    "TavilyAdapter",
    "build_adapters",
    "search_all_adapters",
    "close_adapters",
    "is_valid_product_url",
    "store_from_url",
    "extract_prices",
    "normalize_numbers",
    # hunter
    "AutoHunter",
    "start_auto_hunter",
    "get_auto_hunter",
    "format_deal",
    # engine
    "BlackHuntEngine",
    "get_engine",
]
