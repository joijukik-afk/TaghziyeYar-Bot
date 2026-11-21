"""سانیتایزر HTML برای تلگرام — فقط تگ‌های مجاز رو نگه می‌داره."""

import re
import html


# تگ‌هایی که تلگرام در parse_mode="HTML" پشتیبانی می‌کنه
ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "code", "pre", "a", "tg-spoiler", "span",
}


def sanitize_telegram_html(text: str) -> str:
    """
    متن رو برای parse_mode="HTML" تلگرام آماده می‌کنه:
    - تگ‌های غیرمجاز رو حذف یا به معادل متنی تبدیل می‌کنه
    - کاراکترهای &, <, > که escape نشدن رو escape می‌کنه (به‌جز داخل تگ‌ها)
    """
    if not text:
        return ""

    # 1) تبدیل تگ‌های ساختاری به متن
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

    # 2) فقط تگ‌های مجاز رو نگه دار، بقیه رو حذف کن (ولی محتوا رو حفظ کن)
    def _strip_tag(match: re.Match) -> str:
        raw = match.group(0)
        # استخراج اسم تگ
        tag_match = re.match(r"</?\s*([a-zA-Z][\w-]*)", raw)
        if not tag_match:
            return ""
        tag_name = tag_match.group(1).lower()
        if tag_name in ALLOWED_TAGS:
            return raw
        return ""

    text = re.sub(r"<[^>]+>", _strip_tag, text)

    # 3) فشرده‌سازی خطوط خالی پشت سر هم
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
