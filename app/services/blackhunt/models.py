"""Data models for BlackHunt / AutoHunter."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class DealResult:
    """A single product deal discovered by an adapter."""

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
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    extra: Dict[str, Any] = field(default_factory=dict)

    # -------- derived helpers --------

    @property
    def discount(self) -> float:
        """Best available discount percentage (real wins over listed)."""
        if self.real_discount_percent:
            return float(self.real_discount_percent)
        return float(self.listed_discount_percent or 0)

    @property
    def savings(self) -> int:
        """Amount saved compared to the old price."""
        if self.old_price and self.price and self.old_price > self.price:
            return self.old_price - self.price
        return 0

    @property
    def has_price(self) -> bool:
        return self.price > 0

    def is_qualified(self, min_discount: float) -> bool:
        """Does this deal meet the AutoHunter threshold?"""
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
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in raw.items() if k in allowed})


@dataclass
class HuntReport:
    """Summary of one AutoHunter round."""

    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    groups_count: int = 0
    deals_found: int = 0
    deals_qualified: int = 0
    deals_sent: int = 0
    errors: list[str] = field(default_factory=list)

    def finish(self) -> None:
        self.finished_at = datetime.utcnow()

    @property
    def duration_seconds(self) -> float:
        if not self.finished_at:
            return 0.0
        return (self.finished_at - self.started_at).total_seconds()


__all__ = ["DealResult", "HuntReport"]
