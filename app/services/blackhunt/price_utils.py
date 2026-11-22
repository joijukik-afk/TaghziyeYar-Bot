"""Persian/Arabic digit & currency normalization."""
from __future__ import annotations

import re
from typing import Optional

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = {ord(p): str(i) for i, p in enumerate(_PERSIAN_DIGITS)}
_DIGIT_MAP.update({ord(a): str(i) for i, a in enumerate(_ARABIC_DIGITS)})

_RIAL_WORDS = re.compile(r"\b(ریال|ريال)\b", re.IGNORECASE)
_NUM_RE = re.compile(r"\d[\d,\.]*")


def normalize_digits(text: str) -> str:
    if not text:
        return ""
    return text.translate(_DIGIT_MAP)


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = normalize_digits(text)
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
    text = (
        text.replace("\u200c", " ")
        .replace("\u200f", "")
        .replace("\u200e", "")
    )
    return re.sub(r"\s+", " ", text).strip()


def parse_price(text: str) -> Optional[int]:
    """Parse price string to Toman. Returns None on failure."""
    if not text:
        return None
    raw = normalize_digits(str(text))
    is_rial = bool(_RIAL_WORDS.search(raw))
    m = _NUM_RE.search(raw)
    if not m:
        return None
    number = (
        m.group(0)
        .replace(",", "")
        .replace("\u066c", "")
        .replace(".", "")
    )
    try:
        value = int(number)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value // 10 if is_rial else value


def format_price(value: int) -> str:
    if not value:
        return "0"
    return f"{int(value):,}".replace(",", "٬")


def pct_discount(old_price: int, new_price: int) -> float:
    if not old_price or old_price <= 0 or new_price <= 0:
        return 0.0
    if new_price >= old_price:
        return 0.0
    return round((old_price - new_price) / old_price * 100.0, 1)
