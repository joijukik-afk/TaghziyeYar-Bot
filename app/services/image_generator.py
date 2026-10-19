"""سرویس تولید عکس اختصاصی و شیک برای گروه (با عکس‌های واقعی و باکیفیت)"""

import io
import logging
import random
import os
import httpx
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

logger = logging.getLogger(__name__)

FONT_PATH = "Vazirmatn-Bold.ttf"
FONT_URL = "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Bold.ttf"

# 🖼️ گالری عکس‌های فوق‌العاده حرفه‌ای از غذاهای سالم (کیفیت 4K)
FOOD_IMAGES = [
    "https://images.unsplash.com/photo-1490645935967-10de6ba17061?q=80&w=1024&auto=format&fit=crop", # کاسه سالم
    "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?q=80&w=1024&auto=format&fit=crop", # سالاد رنگارنگ
    "https://images.unsplash.com/photo-1540189549336-e6e99c3679fe?q=80&w=1024&auto=format&fit=crop", # بشقاب رژیمی
    "https://images.unsplash.com/photo-1498837167922-ddd27525d352?q=80&w=1024&auto=format&fit=crop", # میز صبحانه سالم
    "https://images.unsplash.com/photo-1473093295043-cdd812d0e601?q=80&w=1024&auto=format&fit=crop", # پاستا و سبزیجات
    "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?q=80&w=1024&auto=format&fit=crop", # پیتزا (به عنوان غذای فست‌فود سالم)
    "https://images.unsplash.com/photo-1505253716362-afaea1d3d1af?q=80&w=1024&auto=format&fit=crop", # اسموتی و میوه
    "https://images.unsplash.com/photo-1482049016688-2d3e1b311543?q=80&w=1024&auto=format&fit=crop"  # بشقاب حرفه‌ای
]

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

    # انتخاب یک عکس تصادفی از گالری
    image_url = random.choice(FOOD_IMAGES)

    # دانلود عکس
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception as e:
        logger.error("خطا در دریافت عکس: %s", e)
        raise Exception("عدم دسترسی به سرور عکس")

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

    # نوشتن اسم گروه با حاشیه (Stroke) و سایه
    draw.text(
        (x_group, y_group), 
        text_group, 
        font=font_group, 
        fill=(255, 255, 255, 255),
        stroke_width=10,           
        stroke_fill=(0, 0, 0, 255) 
    )

    # خروجی گرفتن
    final_image_io = io.BytesIO()
    img.convert("RGB").save(final_image_io, format="JPEG", quality=95)
    final_image_io.seek(0)
    final_image_io.name = 'cover.jpg'
    
    return final_image_io
