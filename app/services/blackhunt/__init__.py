"""BLACKHUNT IR — موتور شکار تخفیف ایران (نسخه حرفه‌ای)."""
from .engine import get_engine, BlackHuntEngine
from .models import DealResult, SearchStats, SearchIntent
from .auto_hunter import get_auto_hunter, AutoHunter

__all__ = [
    "get_engine", "BlackHuntEngine",
    "DealResult", "SearchStats", "SearchIntent",
    "get_auto_hunter", "AutoHunter",
]
