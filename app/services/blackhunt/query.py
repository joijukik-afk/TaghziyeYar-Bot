"""Search query model + presets for the smart search wizard."""
from dataclasses import dataclass, field
from typing import List

STORES = {
    "digikala": "دیجی‌کالا",
    "torob": "ترب",
    "snappshop": "اسنپ‌شاپ",
}

DISCOUNT_OPTIONS = [0, 10, 20, 30, 40, 50]

SORT_OPTIONS = {
    "smart": "پیشنهاد هوشمند",
    "best_discount": "بیشترین تخفیف",
    "cheapest": "ارزان‌ترین",
    "newest": "جدیدترین",
}

CATEGORY_PRESETS = {
    "mobile": ("📱 موبایل", "گوشی موبایل"),
    "laptop": ("💻 لپ‌تاپ", "لپ تاپ"),
    "headphone": ("🎧 هدفون", "هدفون بلوتوثی"),
    "home": ("🏠 خانه", "لوازم خانگی"),
}


@dataclass
class SearchQuery:
    text: str = ""
    stores: List[str] = field(
        default_factory=lambda: list(STORES.keys())
    )
    min_discount: float = 0.0
    sort: str = "smart"
    max_results: int = 30
    show_unverified: bool = False
