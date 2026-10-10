"""Validation helpers for user inputs."""

import re


AGE_MIN = 18
AGE_MAX = 80

HEIGHT_MIN = 100.0
HEIGHT_MAX = 230.0

WEIGHT_MIN = 30.0
WEIGHT_MAX = 300.0


def parse_int(text: str, min_v: int, max_v: int) -> int:
    """Parse a Persian/Arabic/English integer from text."""
    if text is None:
        raise ValueError("empty")
    # convert Persian and Arabic digits to ASCII
    normalized = _normalize_digits(text.strip())
    # extract first number
    m = re.search(r"-?\d+", normalized)
    if not m:
        raise ValueError("no number found")
    value = int(m.group())
    if value < min_v or value > max_v:
        raise ValueError(f"out of range ({min_v}-{max_v})")
    return value


def parse_float(text: str, min_v: float, max_v: float) -> float:
    if text is None:
        raise ValueError("empty")
    normalized = _normalize_digits(text.strip()).replace("٫", ".").replace(",", ".")
    m = re.search(r"-?\d+(\.\d+)?", normalized)
    if not m:
        raise ValueError("no number found")
    value = float(m.group())
    if value < min_v or value > max_v:
        raise ValueError(f"out of range ({min_v}-{max_v})")
    return value


def _normalize_digits(s: str) -> str:
    """Convert Persian (۰-۹) and Arabic (٠-٩) digits to ASCII."""
    trans = str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
        "01234567890123456789",
    )
    return s.translate(trans)


def validate_gender(text: str) -> str | None:
    """Return 'male' or 'female', or None if invalid."""
    t = text.strip().lower()
    if t in ("مرد", "male", "m", "آقا", "پسر"):
        return "male"
    if t in ("زن", "female", "f", "خانم", "دختر"):
        return "female"
    return None


def validate_goal(text: str) -> str | None:
    t = text.strip().lower()
    mapping = {
        "کاهش وزن": "lose", "لاغری": "lose", "کم کردن وزن": "lose",
        "افزایش وزن": "gain", "چاق شدن": "gain", "وزن گرفتن": "gain",
        "عضله": "muscle", "عضله‌سازی": "muscle", "عضله سازی": "muscle",
        "حفظ وزن": "maintain", "ثابت": "maintain",
        "کیفیت": "quality", "تغذیه سالم": "quality", "بهبود": "quality",
        "ورزشی": "sport", "ورزش": "sport", "ورزشکار": "sport",
    }
    for key, val in mapping.items():
        if key in t:
            return val
    return None


def validate_activity(text: str) -> str | None:
    t = text.strip().lower()
    mapping = {
        "کم‌تحرک": "sedentary", "کم تحرک": "sedentary", "بی‌تحرک": "sedentary",
        "سبک": "light", "کم": "light",
        "متوسط": "moderate", "معمولی": "moderate",
        "زیاد": "high", "بسیار": "high", "شدید": "high", "پر": "high",
    }
    for key, val in mapping.items():
        if key in t:
            return val
    return None
