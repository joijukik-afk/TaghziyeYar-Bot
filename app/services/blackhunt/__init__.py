"""BlackHunt — autonomous Iranian deal hunter."""
from .models import DealResult, SearchIntent, HuntReport
from .adapters import (
    BaseAdapter,
    DigikalaAdapter,
    TorobAdapter,
    SnappShopAdapter,
    MCPAdapter,
    build_adapters,
    close_adapters,
    search_all_adapters,
    is_valid_product_url,
    extract_prices,
    normalize_numbers,
    store_from_url,
)
from .analyzer import (
    VerificationResult,
    PriceVerifier,
    DealRanker,
    analyze_deals,
    deduplicate,
    filter_by_intent,
    format_deal_message,
)
from .engine import (
    HuntEngine,
    SearchStats,
    get_engine,
)
from .auto_hunter import (
    AutoHunter,
    start_auto_hunter,
    get_auto_hunter,
    format_deal,
)

__all__ = [
    # models
    "DealResult",
    "SearchIntent",
    "HuntReport",
    # adapters
    "BaseAdapter",
    "DigikalaAdapter",
    "TorobAdapter",
    "SnappShopAdapter",
    "MCPAdapter",
    "build_adapters",
    "close_adapters",
    "search_all_adapters",
    "is_valid_product_url",
    "extract_prices",
    "normalize_numbers",
    "store_from_url",
    # analyzer
    "VerificationResult",
    "PriceVerifier",
    "DealRanker",
    "analyze_deals",
    "deduplicate",
    "filter_by_intent",
    "format_deal_message",
    # engine
    "HuntEngine",
    "SearchStats",
    "get_engine",
    # auto_hunter
    "AutoHunter",
    "start_auto_hunter",
    "get_auto_hunter",
    "format_deal",
]
