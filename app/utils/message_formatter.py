"""Adds the central signature to every user-facing message."""

import re
from app.config import get_settings

# Telegram max message length is 4096 chars. Keep safety margin.
TELEGRAM_MAX_LEN = 4000


def _strip_html(text: str) -> str:
    """حذف تگ‌های HTML برای محاسبه طول واقعی متن"""
    return re.sub(r'<[^>]+>', '', text)


def with_signature(text: str) -> str:
    """Append the brand signature to a user-facing message safely.

    Empty strings and pure-whitespace strings are returned unchanged.
    If the result would exceed Telegram's limit, we truncate the body
    safely (without breaking HTML tags) and add an ellipsis.
    """
    if not text or not text.strip():
        return text

    # 👈 خواندن امضا از تنظیمات (SSOT)
    signature = get_settings().signature
    if not signature.startswith("\n\n"):
        signature = "\n\n" + signature

    # If already signed, don't double-sign
    if text.rstrip().endswith(signature.strip()):
        return text

    room = TELEGRAM_MAX_LEN - len(signature)

    # 👈 محاسبه طول واقعی متن بدون تگ‌های HTML
    plain_text = _strip_html(text)

    if len(plain_text) <= room:
        return text.rstrip() + signature

    # 👈 اگر متن طولانی بود، بر اساس کلمات برش می‌زنیم تا نیم‌فاصله‌ها خراب نشوند
    words = text.split()
    truncated_text = ""
    current_len = 0

    for word in words:
        # طول کلمه بدون احتساب تگ‌های HTML
        word_len = len(_strip_html(word)) + 1  # +1 for space
        if current_len + word_len > room:
            break
        truncated_text += word + " "
        current_len += word_len

    truncated_text = truncated_text.strip()

    return truncated_text + "…" + signature


def truncate(text: str, limit: int = TELEGRAM_MAX_LEN) -> str:
    """Hard truncate a plain (unsigned) text to fit Telegram."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
