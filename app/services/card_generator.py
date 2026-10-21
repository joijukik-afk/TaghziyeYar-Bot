"""تولید کارت گرافیکی با ترکیب هوش مصنوعی (پس‌زمینه) و متن واضح فارسی"""

import io
import os
import logging
import urllib.parse
import httpx
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter, features
import arabic_reshaper
from bidi.algorithm import get_display

logger = logging.getLogger(__name__)

FONT_PATH = "Vazirmatn-Bold.ttf"
FONT_URL = "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/fonts/ttf/Vazirmatn-Bold.ttf"

HAS_RAQM = features.check("raqm")
logger.info(f"Pillow Raqm Support: {HAS_RAQM}")

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

def _clean_num(val: str) -> str:
    try:
        num = float(val)
        return str(int(num)) if num.is_integer() else str(num)
    except:
        return str(val)

def _draw_text(draw, xy, text, font, fill, anchor="ra"):
    """رسم متن‌های فارسی (RTL)"""
    if not text: return
    text = str(text)
    if HAS_RAQM:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor, direction="rtl")
    else:
        reshaped = arabic_reshaper.reshape(text)
        bidi_text = get_display(reshaped)
        draw.text(xy, bidi_text, font=font, fill=fill, anchor=anchor)

def _draw_num(draw, xy, text, font, fill, anchor="ra"):
    """رسم اعداد (اجبار به چپ‌به‌راست LTR) تا هرگز برعکس نشوند"""
    if not text: return
    text = str(text)
    if HAS_RAQM:
        # دستور صریح ltr به موتور رندر تا عدد را برعکس نکند
        draw.text(xy, text, font=font, fill=fill, anchor=anchor, direction="ltr")
    else:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)

async def generate_ai_health_card(
    name: str, age: str, weight: str, height: str, bmi: str, bmi_status: str, goal: str
) -> io.BytesIO:
    
    await _ensure_font_exists()
    
    prompts = [
        "Abstract dark blue and teal gradient background, smooth glowing waves, professional, minimalistic, no text, no people, no objects, no faces, high resolution.",
        "Abstract dark emerald green and gold gradient background, smooth glowing curves, professional, minimalistic, no text, no people, no objects, high resolution.",
        "Abstract dark purple and cyan gradient background, smooth glowing lines, professional, minimalistic, no text, no people, no objects, high resolution."
    ]
    prompt = random.choice(prompts)
    encoded_prompt = urllib.parse.quote(prompt)
    ai_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=640&nologo=true&model=flux"
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(ai_url)
            resp.raise_for_status()
            bg_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=25))
    except Exception as e:
        logger.error(f"خطا در دریافت پس‌زمینه AI: {e}")
        bg_img = Image.new("RGBA", (1024, 640), "#0f172a")

    overlay = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(0, 0), bg_img.size], fill=(15, 23, 42, 200)) 
    bg_img = Image.alpha_composite(bg_img, overlay)
    
    width, height = bg_img.size

    glass_box = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    glass_draw = ImageDraw.Draw(glass_box)
    glass_draw.rounded_rectangle([(40, 40), (width-40, height-40)], radius=40, fill=(255, 255, 255, 15), outline=(56, 189, 248, 100), width=2)
    bg_img = Image.alpha_composite(bg_img, glass_box)
    draw = ImageDraw.Draw(bg_img)

    try:
        font_title = ImageFont.truetype(FONT_PATH, 42)
        font_name = ImageFont.truetype(FONT_PATH, 55)
        font_num = ImageFont.truetype(FONT_PATH, 36)   
        font_label = ImageFont.truetype(FONT_PATH, 24) 
        font_bmi = ImageFont.truetype(FONT_PATH, 85)
        font_small = ImageFont.truetype(FONT_PATH, 20)
    except Exception as e:
        logger.error("فونت لود نشد: %s", e)
        return io.BytesIO()

    # ۱. هدر
    _draw_text(draw, (width//2, 85), "پاسپورت سلامت تغذیه‌یار", font_title, "#38bdf8", anchor="mm")
    draw.line([(300, 125), (width-300, 125)], fill="#38bdf8", width=2)
    
    # ۲. نام
    _draw_text(draw, (width - 90, 160), name, font_name, "#f8fafc", anchor="ra")

    # ۳. اطلاعات (عدد و کلمه کاملاً جدا از هم رسم می‌شوند)
    start_y = 240
    gap = 75
    
    # سن
    _draw_num(draw, (width - 180, start_y), _clean_num(age), font_num, "#e2e8f0", anchor="ra")
    _draw_text(draw, (width - 70, start_y), "سال", font_label, "#94a3b8", anchor="ra")
    
    # قد
    _draw_num(draw, (width - 200, start_y + gap), _clean_num(height), font_num, "#e2e8f0", anchor="ra")
    _draw_text(draw, (width - 70, start_y + gap), "سانتی‌متر", font_label, "#94a3b8", anchor="ra")
    
    # وزن
    _draw_num(draw, (width - 200, start_y + gap*2), _clean_num(weight), font_num, "#e2e8f0", anchor="ra")
    _draw_text(draw, (width - 70, start_y + gap*2), "کیلوگرم", font_label, "#94a3b8", anchor="ra")

    # ۴. کادر BMI
    box_x1, box_y1 = 80, 190
    box_x2, box_y2 = 450, 470
    
    if "نرمال" in bmi_status: status_color = "#10b981" 
    elif "اضافه" in bmi_status or "چاقی" in bmi_status: status_color = "#ef4444" 
    else: status_color = "#f59e0b" 
    
    draw.rounded_rectangle([box_x1, box_y1, box_x2, box_y2], radius=30, fill=(30, 41, 59, 240), outline=status_color, width=3)
    
    _draw_text(draw, ((box_x1+box_x2)//2, box_y1 + 60), "شاخص توده بدنی (BMI)", font_label, "#cbd5e1", anchor="mm")
    _draw_num(draw, ((box_x1+box_x2)//2, box_y1 + 170), _clean_num(bmi), font_bmi, status_color, anchor="mm")
    _draw_text(draw, ((box_x1+box_x2)//2, box_y1 + 250), bmi_status, font_num, status_color, anchor="mm")

    # ۵. بخش پایین (مختصات بالاتر آمد تا بریده نشود)
    draw.line([(90, 480), (width-90, 480)], fill="#334155", width=2)

    # هدف
    _draw_text(draw, (width - 90, 510), "هدف فعلی:", font_label, "#94a3b8", anchor="ra")
    _draw_text(draw, (width - 90, 550), goal, font_num, "#38bdf8", anchor="ra")

    # متخصص
    _draw_text(draw, (90, 510), "زیر نظر متخصص تغذیه:", font_small, "#94a3b8", anchor="la")
    _draw_text(draw, (90, 550), "علی اکبر ابراهیم پور", font_num, "#f8fafc", anchor="la")
    
    # آیدی
    _draw_text(draw, (width//2, 595), "@AliAkbaro0", font_small, "#64748b", anchor="mm")

    img_io = io.BytesIO()
    bg_img.convert("RGB").save(img_io, format="JPEG", quality=95)
    img_io.seek(0)
    img_io.name = 'ai_health_card.jpg'
    return img_io
