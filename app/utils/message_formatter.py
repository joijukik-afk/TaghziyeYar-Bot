"""Adds the central signature to every user-facing message."""

# Telegram max message length is 4096 chars. Keep safety margin.
TELEGRAM_MAX_LEN = 4000

# 👇 امضای جدید ربات (دیگه از تنظیمات خونده نمیشه و اسم متخصص توش نیست)
NEW_SIGNATURE = "\n\n🌱 تغذیه‌یار | دستیار هوشمند شما"


def with_signature(text: str) -> str:
    """Append the brand signature to a user-facing message.

    Empty strings and pure-whitespace strings are returned unchanged.
    If the result would exceed Telegram's limit, we truncate the body
    (never the signature) and add an ellipsis.
    """
    if not text or not text.strip():
        return text

    signature = NEW_SIGNATURE

    # If already signed, don't double-sign
    if text.rstrip().endswith(signature.strip()):
        return text

    room = TELEGRAM_MAX_LEN - len(signature)
    body = text.rstrip()
    if len(body) > room:
        body = body[: room - 1].rstrip() + "…"

    return body + signature


def truncate(text: str, limit: int = TELEGRAM_MAX_LEN) -> str:
    """Hard truncate a plain (unsigned) text to fit Telegram."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
