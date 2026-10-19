"""سرویس تولید عکس اختصاصی و شیک برای گروه"""

import io
import logging
import random
import urllib.parse
import os
import httpx
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

logger = logging.getLogger(__name__)

FONT_PATH = "Vazirmatn-Bold.ttf"
FONT_URL = "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Bold.ttf"

async def _ensure_font_exists():
    if not os.path.exists(FONT_PATH):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(FONT_URL, follow_redirects=True)
                if resp.status_code == 200:
                    with open(FONT_PATH, "wb") as f:
                        f.write(resp.content)
        except Exception as e:
            logger.warning("خطا در دانلود فونت: %s", e)

def _reshape_persian_text(text: str) -> str:
    reshaped_text = arabic_reshaper.reshape(text)
    return get_display(reshaped_text)

async def generate_group_cover(group_name: str) -> io.BytesIO:
    await _ensure_font_exists()

    # 🎯 پرامپت کوتاه و ساده برای غذا
    base_prompt = "delicious_healthy_food_platter, colorful_salad, fresh_fruits, professional_food_photography, 4k"
    encoded_prompt = urllib.parse.quote(base_prompt)
    random_seed = random.randint(1, 999999) 

    image_url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width=1024&height=1024&nologo=true&seed={random_seed}"
    )

    img = None
    try:
        # افزایش زمان انتظار به ۱۲۰ ثانیه (چون تولید عکس با AI گاهی زمان‌بر است)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception as e:
        logger.error("خطا در دریافت عکس از هوش مصنوعی: %s", e)
        # 🛠️ سیستم پشتیبان: اگر هوش مصنوعی عکس نداد، از این عکس ثابت استفاده کن
        logger.info("استفاده از عکس پشتیبان برای کاور...")
        fallback_url = "https://images.unsplash.com/photo-1490645935967-10de6ba17061?q=80&w=1024&auto=format&fit=crop"
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(fallback_url)
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        except Exception as fallback_e:
            logger.error("خطای پشتیبان هم رخ داد: %s", fallback_e)
            raise Exception("عدم دسترسی به هیچ سرور عکسی")

    # آماده‌سازی متن (فقط اسم گروه)
    text_group = _reshape_persian_text(group_name)

    try:
        font_group = ImageFont.truetype(FONT_PATH, 130)
    except Exception:
        font_group = ImageFont.load_default()

    draw = ImageDraw.Draw(img)
    width, height = img.size
    
    # محاسبه موقعیت برای وسط‌چین کردن
    bbox_group = draw.textbbox((0, 0), text_group, font=font_group)
    w_group, h_group = bbox_group[2] - bbox_group[0], bbox_group[3] - bbox_group[1]
    
    x_group = (width - w_group) / 2
    y_group = (height / 2) - (h_group / 2) 

    # نوشتن اسم گروه با حاشیه (Stroke) و سایه برای خوانایی بالا
    draw.text(
        (x_group, y_group), 
        text_group, 
        font=font_group, 
        fill=(255, 255, 255, 255), # متن سفید
        stroke_width=10,           # حاشیه ضخیم
        stroke_fill=(0, 0, 0, 255) # حاشیه مشکی
    )

    # خروجی گرفتن
    final_image_io = io.BytesIO()
    img.convert("RGB").save(final_image_io, format="JPEG", quality=95)
    final_image_io.seek(0)
    final_image_io.name = 'cover.jpg'
    
    return final_image_io
