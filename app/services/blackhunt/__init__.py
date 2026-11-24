"""Public API for the BlackHunt package."""

from app.services.blackhunt.engine import HuntEngine, get_engine
from app.services.blackhunt.auto_hunter import (
    AutoHunter,
    get_auto_hunter,
    start_auto_hunter,
    format_deal,
)
from app.services.blackhunt.models import DealResult, HuntReport
from app.services.blackhunt.query import (
    SearchQuery,
    STORES,
    SORT_OPTIONS,
    DISCOUNT_OPTIONS,
    CATEGORY_PRESETS,
)

__all__ = [
    "HuntEngine",
    "get_engine",
    "AutoHunter",
    "get_auto_hunter",
    "start_auto_hunter",
    "format_deal",
    "DealResult",
    "HuntReport",
    "SearchQuery",
    "STORES",
    "SORT_OPTIONS",
    "DISCOUNT_OPTIONS",
    "CATEGORY_PRESETS",
]
