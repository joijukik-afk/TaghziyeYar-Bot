"""Data models for BlackHunt / AutoHunter."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DealResult:
    title: str
    product_url: str
    store: str = "unknown"
    price: int = 0
    old_price: int = 0
    listed_discount_percent: float = 0.0
    real_discount_percent: float = 0.0
    source: str = ""
    currency: str = "IRR"
    image_url: Optional[str] = None
    availability: str = "unknown"
    fetched_at: datetime = field(default_factory=_utcnow)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def discount(self) -> float:
        return float(
            self.real_discount_percent
            or self.listed_discount_percent
            or 0.0
        )

    @property
    def savings(self) -> int:
        if self.old_price and self.price and self.old_price > self.price:
            return int(self.old_price - self.price)
        return 0

    @property
    def has_price(self) -> bool:
        return self.price > 0

    def is_qualified(self, min_discount: float) -> bool:
        return self.has_price and self.discount >= float(min_discount or 0)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["fetched_at"] = self.fetched_at.isoformat()
        data["discount"] = self.discount
        data["savings"] = self.savings
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DealResult":
        raw = dict(data or {})
        fetched = raw.get("fetched_at")
        if isinstance(fetched, str):
            try:
                raw["fetched_at"] = datetime.fromisoformat(fetched)
            except ValueError:
                raw.pop("fetched_at", None)
        raw.pop("discount", None)
        raw.pop("savings", None)
        allowed = set(cls.__dataclass_fields__.keys())
        return cls(**{k: v for k, v in raw.items() if k in allowed})


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
class HuntReport:
    started_at: datetime = field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None
    groups_count: int = 0
    deals_found: int = 0
    deals_qualified: int = 0
    deals_sent: int = 0
    duplicates_skipped: int = 0
    errors: List[str] = field(default_factory=list)

    def finish(self) -> None:
        self.finished_at = _utcnow()

    @property
    def duration_seconds(self) -> float:
        end = self.finished_at or _utcnow()
        return (end - self.started_at).total_seconds()


__all__ = ["DealResult", "SearchIntent", "HuntReport"]
