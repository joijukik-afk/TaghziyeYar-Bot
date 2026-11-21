"""سانیتایزر HTML برای تلگرام — فقط تگ‌های مجاز رو نگه می‌داره."""

import re
import html


ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "code", "pre", "a", "tg-spoiler", "span",
}


def sanitize_telegram_html(text: str) -> str:
    """متن رو برای parse_mode="HTML" تلگرام آماده می‌کنه."""
    if not text:
        return ""

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?ul[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?ol[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<blockquote[^>]*>", "> ", text, flags=re.IGNORECASE)
    text = re.sub(r"</blockquote>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(div|section|article)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?h[1-6][^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<hr\s*/?>", "─" * 20, text, flags=re.IGNORECASE)

    def _strip_tag(match: re.Match) -> str:
        raw = match.group(0)
        tag_match = re.match(r"</?\s*([a-zA-Z][\w-]*)", raw)
        if not tag_match:
            return ""
        tag_name = tag_match.group(1).lower()
        if tag_name in ALLOWED_TAGS:
            return raw
        return ""

    text = re.sub(r"<[^>]+>", _strip_tag, text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
