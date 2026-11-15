"""Validation helpers for user inputs (Persian-first errors)."""

import re

AGE_MIN = 18
AGE_MAX = 80

HEIGHT_MIN = 100.0
HEIGHT_MAX = 230.0

WEIGHT_MIN = 30.0
WEIGHT_MAX = 300.0

# 👈 پیام‌های خطای فارسی
_ERR_EMPTY = "لطفاً یک مقدار وارد کنید."
_ERR_NO_NUMBER = "عدد معتبری پیدا نشد. لطفاً یک عدد وارد کنید."
_ERR_DECIMAL = "لطفاً یک عدد صحیح (بدون اعشار) وارد کنید."

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
_ASCII_DIGITS = "01234567890123456789"
_TRANS = str.maketrans(_PERSIAN_DIGITS, _ASCII_DIGITS)


def _normalize_digits(s: str) -> str:
    """تبدیل اعداد فارسی و عربی به ASCII."""
    return s.translate(_TRANS)


def _range_str(min_v, max_v) -> str:
    """نمایش تمیز بازه (حذف .0 اضافی)"""
    def fmt(v):
        return str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
    return f"{fmt(min_v)} و {fmt(max_v)}"


def parse_int(text: str | None, min_v: int, max_v: int, field: str = "مقدار") -> int:
    """پارس عدد صحیح با پیام خطای فارسی."""
    if text is None or not str(text).strip():
        raise ValueError(_ERR_EMPTY)

    normalized = _normalize_digits(str(text).strip())

    # 👈 رد کردن اعشار برای فیلدهای صحیح (مثل سن)
    if re.search(r"\d+[.,٫]\d+", normalized):
        raise ValueError(_ERR_DECIMAL)

    m = re.search(r"-?\d+", normalized)
    if not m:
        raise ValueError(_ERR_NO_NUMBER)

    value = int(m.group())
    if value < min_v or value > max_v:
        raise ValueError(
            f"{field} باید بین {_range_str(min_v, max_v)} باشد. "
            f"(مقدار وارد شده: {value})"
        )
    return value


def parse_float(text: str | None, min_v: float, max_v: float, field: str = "مقدار") -> float:
    """پارس عدد اعشاری با پیام خطای فارسی."""
    if text is None or not str(text).strip():
        raise ValueError(_ERR_EMPTY)

    normalized = _normalize_digits(str(text).strip()).replace("٫", ".")

    # 👈 تشخیص جداکننده هزارگان: اگر الگوی 1,000 داشت، کاماها حذف می‌شوند
    if re.search(r"\d{1,3}(,\d{3})+", normalized):
        normalized = normalized.replace(",", "")
    else:
        # در غیر این صورت، کاما به عنوان اعشار تفسیر می‌شود (مثل 75,5)
        normalized = normalized.replace(",", ".")

    m = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not m:
        raise ValueError(_ERR_NO_NUMBER)

    value = float(m.group())
    if value < min_v or value > max_v:
        raise ValueError(
            f"{field} باید بین {_range_str(min_v, max_v)} باشد. "
            f"(مقدار وارد شده: {value})"
        )
    return value


def _match_longest(text: str, mapping: dict[str, str]) -> str | None:
    """
    تطابق هوشمند:
    1. اول Exact Match (دقیق)
    2. سپس Longest Match (طولانی‌ترین کلید)
    """
    t = text.strip().lower()
    if not t:
        return None

    # مرحله ۱: تطابق دقیق
    for key, val in mapping.items():
        if t == key.lower():
            return val

    # مرحله ۲: طولانی‌ترین کلید موجود
    for key in sorted(mapping, key=len, reverse=True):
        if key.lower() in t:
            return mapping[key]

    return None


def validate_gender(text: str) -> str | None:
    """برمی‌گرداند 'male' یا 'female' یا None."""
    mapping = {
        "مرد": "male", "آقا": "male", "پسر": "male",
        "male": "male", "m": "male",
        "زن": "female", "خانم": "female", "دختر": "female",
        "female": "female", "f": "female",
    }
    return _match_longest(text, mapping)


def validate_goal(text: str) -> str | None:
    mapping = {
        "کاهش وزن": "lose", "کم کردن وزن": "lose", "لاغری": "lose",
        "افزایش وزن": "gain", "وزن گرفتن": "gain", "چاق شدن": "gain",
        "عضله‌سازی": "muscle", "عضله سازی": "muscle", "عضله": "muscle",
        "حفظ وزن": "maintain", "ثابت نگه داشتن": "maintain", "ثابت": "maintain",
        "بهبود کیفیت": "quality", "تغذیه سالم": "quality", "کیفیت": "quality",
        "هدف ورزشی": "sport", "ورزشکار": "sport", "ورزشی": "sport", "ورزش": "sport",
    }
    return _match_longest(text, mapping)


def validate_activity(text: str) -> str | None:
    mapping = {
        "کم‌تحرک": "sedentary", "کم تحرک": "sedentary",
        "بی‌تحرک": "sedentary", "بی تحرک": "sedentary",
        "فعالیت سبک": "light", "سبک": "light",
        "فعالیت متوسط": "moderate", "متوسط": "moderate", "معمولی": "moderate",
        "فعالیت زیاد": "high", "فعالیت شدید": "high",
        "زیاد": "high", "شدید": "high", "بسیار فعال": "high",
    }
    return _match_longest(text, mapping)
