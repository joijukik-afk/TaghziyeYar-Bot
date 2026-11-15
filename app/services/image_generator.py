"""سرویس تولید عکس اختصاصی و شیک برای گروه (با عکس‌های واقعی و باکیفیت)"""

import io
import logging
import random
import os
import asyncio
import httpx
from PIL import Image, ImageDraw, ImageFont, features
import arabic_reshaper
from bidi.algorithm import get_display

logger = logging.getLogger(__name__)

# 👈 مسیر مطلق فونت (مستقل از CWD)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FONT_PATH = os.path.join(BASE_DIR, "Vazirmatn-Bold.ttf")
FONT_URL = "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/fonts/ttf/Vazirmatn-Bold.ttf"

HAS_RAQM = features.check("raqm")

FOOD_IMAGES = [
    "https://images.unsplash.com/photo-1490645935967-10de6ba17061?q=80&w=1024&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?q=80&w=1024&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?q=80&w=1024&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1498837167922-ddd27525d352?q=80&w=1024&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1473093295043-cdd812d0e601?q=80&w=1024&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?q=80&w=1024&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1505253716362-afaea1d3d1af?q=80&w=1024&auto=format&fit=crop",
    "https://images.unsplash.com/photo-1482049016688-2d3e1b311543?q=80&w=1024&auto=format&fit=crop",
]


class CoverGenerationError(Exception):
    pass


async def _ensure_font_exists() -> bool:
    if os.path.exists(FONT_PATH):
        return True
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(FONT_URL, follow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 1000:
                await asyncio.to_thread(_write_file, FONT_PATH, resp.content)
                logger.info("Font downloaded successfully.")
                return True
    except Exception as e:
        logger.error("خطا در دانلود فونت: %s", e)
    return False


def _write_file(path: str, content: bytes):
    with open(path, "wb") as f:
        f.write(content)


def _reshape_persian_text(text: str) -> str:
    if HAS_RAQM:
        return text
    reshaped_text = arabic_reshaper.reshape(text)
    return get_display(reshaped_text)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, initial_size: int = 130) -> ImageFont.FreeTypeFont:
    size = initial_size
    while size > 40:
        try:
            font = ImageFont.truetype(FONT_PATH, size)
        except Exception:
            font = ImageFont.load_default()
            return font

        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=10)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            return font
        size -= 10

    try:
        return ImageFont.truetype(FONT_PATH, 40)
    except Exception:
        return ImageFont.load_default()


def _truncate_text_to_fit(draw, text: str, font, max_width: int, stroke_width: int = 10) -> str:
    ellipsis = "…"
    bbox = draw.textbbox((0, 0), text + ellipsis, font=font, stroke_width=stroke_width)
    if bbox[2] - bbox[0] <= max_width:
        return text

    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = text[:mid] + ellipsis
        bbox = draw.textbbox((0, 0), candidate, font=font, stroke_width=stroke_width)
        if bbox[2] - bbox[0] <= max_width:
            low = mid
        else:
            high = mid - 1
    return text[:low] + ellipsis if low > 0 else ellipsis


def _compose_cover_sync(image_bytes: bytes, group_name: str) -> io.BytesIO:
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception as e:
        logger.error("عکس دریافتی معتبر نیست: %s", e)
        raise CoverGenerationError("فایل دریافتی یک عکس معتبر نیست.")

    safe_name = (group_name or "گروه تغذیه").strip()[:100]
    text_group = _reshape_persian_text(safe_name)

    try:
        temp_font = ImageFont.truetype(FONT_PATH, 130)
    except Exception:
        temp_font = ImageFont.load_default()

    draw = ImageDraw.Draw(img)
    width, height = img.size
    max_text_width = int(width * 0.9)

    font_group = _fit_font(draw, text_group, max_text_width, initial_size=130)
    text_group = _truncate_text_to_fit(draw, text_group, font_group, max_text_width, stroke_width=10)

    stroke = 10
    bbox_group = draw.textbbox((0, 0), text_group, font=font_group, stroke_width=stroke)
    w_group = bbox_group[2] - bbox_group[0]
    h_group = bbox_group[3] - bbox_group[1]
    x_group = (width - w_group) / 2
    y_group = (height - h_group) / 2

    if HAS_RAQM:
        draw.text(
            (x_group, y_group), text_group, font=font_group,
            fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255),
            direction="rtl",
        )
    else:
        draw.text(
            (x_group, y_group), text_group, font=font_group,
            fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255),
        )

    final_image_io = io.BytesIO()
    img.convert("RGB").save(final_image_io, format="JPEG", quality=95)
    final_image_io.seek(0)
    final_image_io.name = "cover.jpg"
    return final_image_io


async def generate_group_cover(group_name: str) -> io.BytesIO:
    if not await _ensure_font_exists():
        raise CoverGenerationError("فونت فارسی در دسترس نیست و دانلود آن ناموفق بود.")

    image_url = random.choice(FOOD_IMAGES)

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            image_bytes = resp.content
            if not image_bytes or len(image_bytes) < 1000:
                raise CoverGenerationError("عکس دریافتی خالی یا بسیار کوچک است.")
    except CoverGenerationError:
        raise
    except Exception as e:
        logger.error("خطا در دریافت عکس: %s", e, exc_info=True)
        raise CoverGenerationError("عدم دسترسی به سرور عکس")

    return await asyncio.to_thread(_compose_cover_sync, image_bytes, group_name)
