"""مدل‌های داده BLACKHUNT."""
from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class DealResult:
    product_name: str
    store: str
    product_url: str
    current_price: Optional[int] = None
    listed_old_price: Optional[int] = None
    listed_discount_percent: Optional[int] = None
    real_discount_percent: Optional[int] = None
    marketplace_median: Optional[int] = None
    seller: Optional[str] = None
    availability: Optional[str] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    image_url: Optional[str] = None
    deal_score: float = 0.0
    confidence_score: float = 0.0
    discount_status: str = "insufficient_data"
    verified_at: str = ""
    source_provider: str = ""

@dataclass
class SearchIntent:
    intent_type: str = "specific_product"
    queries: List[str] = field(default_factory=list)
    category: Optional[str] = None
    brands: List[str] = field(default_factory=list)
    min_discount: Optional[int] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    must_be_in_stock: bool = True
    original_request: str = ""

@dataclass
class SearchStats:
    total_found: int = 0
    total_verified: int = 0
    sources_used: List[str] = field(default_factory=list)
    sources_failed: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    queries_run: int = 0
    results_filtered: int = 0
