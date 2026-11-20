"""سرویس ساخت استیکر متنی با پشتیبانی کامل از فارسی.

ویژگی‌ها:
- پشتیبانی از Raqm (اگر نصب باشد) برای بهترین کیفیت shaping
- Fallback به arabic_reshaper + python-bidi
- سایز نهایی دقیقاً 512×512 (استاندارد تلگرام)
- سایز فونت خودکار و درشت (تا 120px)
- پشتیبانی از ۴ استایل: dark, light, transparent, gradient
- خروجی زیر 500KB (با fallback به WEBP)
"""
import io
import logging
from pathlib import Path
from typing import Optional, List, Tuple

import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont, features

logger = logging.getLogger(__name__)

# ==================== ثابت‌ها ====================
STICKER_SIZE = 512
MAX_BYTES = 500 * 1024
MIN_FONT = 22
MAX_FONT = 120
PADDING = 36
LINE_SPACING = 1.35

# مسیرهای جستجوی فونت — اولین موجود استفاده می‌شود
FONT_CANDIDATES: List[str] = [
    "assets/fonts/Vazirmatn-Bold.ttf",
    "assets/fonts/Vazirmatn-Regular.ttf",
    "assets/fonts/Vazir-Bold.ttf",
    "assets/fonts/Vazir.ttf",
    "assets/fonts/Sahel-Bold.ttf",
    "assets/fonts/Dana-Bold.ttf",
    "assets/fonts/IRANSans-Bold.ttf",
    "assets/fonts/IRANSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

# بررسی در دسترس بودن Raqm
_RAQM = features.check("raqm")
if _RAQM:
    logger.info("STICKER: RAQM available — using native Complex Text Layout")
else:
    logger.info("STICKER: RAQM not available — using arabic_reshaper + bidi")


# ==================== فونت ====================
def _find_font() -> Optional[str]:
    """اولین فونت موجود را از لیست برمی‌گرداند."""
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return path
    logger.error("STICKER: no Persian font found in FONT_CANDIDATES")
    return None


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """فونت را با سایز مشخص بارگذاری می‌کند."""
    path = _find_font()
    if not path:
        return ImageFont.load_default()
    try:
        if _RAQM:
            return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
        return ImageFont.truetype(path, size)
    except Exception as e:
        logger.warning(f"STICKER: font load failed: {e}")
        return ImageFont.load_default()


# ==================== آماده‌سازی متن ====================
def _prepare(text: str) -> str:
    """متن فارسی را برای رندر آماده می‌کند."""
    if _RAQM:
        # Raqm خودش bidi و shaping را انجام می‌دهد
        return text
    # fallback: اول reshape بعد bidi
    reshaped = arabic_reshaper.reshape(text)
    return get_display(reshaped)


def _measure(text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    """عرض و ارتفاع متن آماده‌شده را برمی‌گرداند."""
    prepared = _prepare(text)
    dummy = Image.new("RGB", (1, 1))
    draw = ImageDraw.Draw(dummy)
    try:
        bbox = draw.textbbox((0, 0), prepared, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        return draw.textsize(prepared, font=font)


# ==================== شکستن متن ====================
def _wrap_logical(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    """متن را به خطوطی با عرض محدود می‌شکند (قبل از bidi)."""
    lines: List[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split()
        current = ""
        for word in words:
            test = f"{current} {word}".strip() if current else word
            w, _ = _measure(test, font)
            if w <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines


# ==================== محاسبه بهترین فونت ====================
def _fit_text(
    text: str, max_width: int, max_height: int
) -> Tuple[ImageFont.FreeTypeFont, List[str]]:
    """بهترین سایز فونت را انتخاب می‌کند تا متن در قاب جا شود."""
    for size in range(MAX_FONT, MIN_FONT - 1, -4):
        font = _load_font(size)
        lines = _wrap_logical(text, font, max_width)
        if not lines:
            continue
        line_height = int(size * LINE_SPACING)
        if line_height * len(lines) <= max_height:
            return font, lines
    # اگر هیچ سایزی جا نشد
    font = _load_font(MIN_FONT)
    return font, _wrap_logical(text, font, max_width)


# ==================== پس‌زمینه ====================
def _make_background(style: str) -> Image.Image:
    """تصویر پس‌زمینه را بر اساس استایل می‌سازد."""
    if style == "transparent":
        return Image.new("RGBA", (STICKER_SIZE, STICKER_SIZE), (0, 0, 0, 0))
    if style == "light":
        return Image.new("RGBA", (STICKER_SIZE, STICKER_SIZE), (255, 255, 255, 255))
    if style == "gradient":
        base = Image.new("RGBA", (STICKER_SIZE, STICKER_SIZE), (0, 0, 0, 0))
        draw = ImageDraw.Draw(base)
        top, bottom = (18, 18, 28), (48, 32, 58)
        for y in range(STICKER_SIZE):
            t = y / (STICKER_SIZE - 1)
            draw.line(
                [(0, y), (STICKER_SIZE, y)],
                fill=(
                    int(top[0] * (1 - t) + bottom[0] * t),
                    int(top[1] * (1 - t) + bottom[1] * t),
                    int(top[2] * (1 - t) + bottom[2] * t),
                    255,
                ),
            )
        return base
    # پیش‌فرض: dark
    return Image.new("RGBA", (STICKER_SIZE, STICKER_SIZE), (20, 20, 30, 255))


def _text_color(style: str) -> Tuple[int, int, int, int]:
    """رنگ متن بر اساس استایل."""
    if style == "light":
        return (25, 25, 35, 255)
    return (245, 245, 250, 255)


# ==================== تابع اصلی ====================
def create_sticker(text: str, style: str = "dark") -> io.BytesIO:
    """
    استیکر 512×512 از متن فارسی می‌سازد.

    Args:
        text: متن ورودی (می‌تواند شامل \\n باشد)
        style: "dark" | "light" | "transparent" | "gradient"

    Returns:
        BytesIO حاوی فایل PNG (یا WEBP در صورت حجم بالا) آماده برای ارسال به تلگرام
    """
    if not text or not text.strip():
        text = "..."
    if style not in ("dark", "light", "transparent", "gradient"):
        style = "dark"

    max_width = STICKER_SIZE - 2 * PADDING
    max_height = STICKER_SIZE - 2 * PADDING

    font, lines = _fit_text(text, max_width, max_height)
    font_size = getattr(font, "size", MIN_FONT)
    line_height = int(font_size * LINE_SPACING)

    img = _make_background(style)
    draw = ImageDraw.Draw(img)
    color = _text_color(style)

    # شروع از مرکز عمودی
    y = (STICKER_SIZE - line_height * len(lines)) // 2

    for line in lines:
        prepared = _prepare(line)
        w, _ = _measure(line, font)
        x = (STICKER_SIZE - w) // 2

        # سایه برای خوانایی
        if style != "transparent":
            shadow = (0, 0, 0, 180) if style != "light" else (0, 0, 0, 60)
            draw.text((x + 2, y + 2), prepared, font=font, fill=shadow)
        else:
            for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                draw.text((x + dx, y + dy), prepared, font=font, fill=(0, 0, 0, 200))

        draw.text((x, y), prepared, font=font, fill=color)
        y += line_height

    # خروجی PNG
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    out.seek(0)

    # اگر > 500KB شد، WEBP
    if out.getbuffer().nbytes > MAX_BYTES:
        out = io.BytesIO()
        img.save(out, format="WEBP", quality=85, method=6)
        out.seek(0)

    return out
