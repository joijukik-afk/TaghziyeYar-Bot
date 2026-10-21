"""تولید کارت گرافیکی با ترکیب هوش مصنوعی (پس‌زمینه) و متن واضح فارسی"""

import io
import os
import logging
import urllib.parse
import httpx
import re
import random
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

logger = logging.getLogger(__name__)

FONT_PATH = "Vazirmatn-Bold.ttf"
FONT_URL = "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/fonts/ttf/Vazirmatn-Bold.ttf"

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

def _shape_text(text: str) -> str:
    if not text: return ""
    try:
        text = re.sub(r'[^\w\s\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF\.\!\-\+\%\(\)\/]', '', str(text))
        config = {'delete_harakat': False, 'support_ligatures': True, 'RIAL': False}
        reshaped = arabic_reshaper.reshape(text.strip(), configuration=config)
        return get_display(reshaped)
    except Exception as e:
        return str(text)

def _format_num(val: str) -> str:
    try:
        num = float(val)
        if num.is_integer(): return str(int(num))
        return str(num)
    except:
        return str(val)

async def generate_ai_health_card(
    name: str, age: str, weight: str, height: str, bmi: str, bmi_status: str, goal: str
) -> io.BytesIO:
    
    await _ensure_font_exists()
    
    # لیست پس‌زمینه‌های حرفه‌ای و رندوم (آبی، فیروزه‌ای، طلایی، پزشکی، مدرن)
    prompts = [
        "A highly professional, modern, dark-themed digital ID card template background. Dark blue gradient with glassmorphism, glowing neon blue accents. Blank empty space in the center for text. 8k, clean UI design.",
        "A futuristic medical ID card background, dark teal and navy blue colors, glass morphism, subtle glowing health symbols, abstract particles. 8k, clean UI.",
        "An elegant dark green and gold digital ID card background, professional health and wellness theme, smooth gradients, minimalist design. 8k, clean UI.",
        "A sleek modern dark purple and cyan ID card background, high-tech health dashboard style, glassmorphism effects, glowing lines. 8k, clean UI.",
        "A professional dark gray and emerald green ID card background, subtle geometric patterns, corporate health theme, glassmorphism. 8k, clean UI."
    ]
    prompt = random.choice(prompts)
    
    encoded_prompt = urllib.parse.quote(prompt)
    ai_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=640&nologo=true&model=flux"
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(ai_url)
            resp.raise_for_status()
            bg_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception as e:
        logger.error(f"خطا در دریافت پس‌زمینه AI: {e}")
        bg_img = Image.new("RGBA", (1024, 640), "#0f172a")

    overlay = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(0, 0), bg_img.size], fill=(15, 23, 42, 150)) # لایه تاریک برای خوانایی
    bg_img = Image.alpha_composite(bg_img, overlay)
    draw = ImageDraw.Draw(bg_img)

    try:
        font_title = ImageFont.truetype(FONT_PATH, 38)
        font_name = ImageFont.truetype(FONT_PATH, 60)
        font_value = ImageFont.truetype(FONT_PATH, 36)
        font_label = ImageFont.truetype(FONT_PATH, 24)
        font_bmi = ImageFont.truetype(FONT_PATH, 80)
        font_small = ImageFont.truetype(FONT_PATH, 20)
    except Exception as e:
        logger.error("فونت لود نشد: %s", e)
        return io.BytesIO()

    width, height = bg_img.size

    # هدر کارت
    draw.text((width//2, 50), _shape_text("پاسپورت سلامت تغذیه‌یار"), font=font_title, fill="#38bdf8", anchor="mm")
    draw.text((width - 80, 140), _shape_text(name), font=font_name, fill="#f8fafc", anchor="ra")

    # اطلاعات سمت راست
    start_y = 250
    gap = 75
    
    draw.text((width - 80, start_y), _shape_text("سن"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 200, start_y), _shape_text(f"{_format_num(age)} سال"), font=font_value, fill="#e2e8f0", anchor="ra")
    
    draw.text((width - 80, start_y + gap), _shape_text("قد"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 200, start_y + gap), _shape_text(f"{_format_num(height)} سانتی‌متر"), font=font_value, fill="#e2e8f0", anchor="ra")
    
    draw.text((width - 80, start_y + gap*2), _shape_text("وزن"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 200, start_y + gap*2), _shape_text(f"{_format_num(weight)} کیلوگرم"), font=font_value, fill="#e2e8f0", anchor="ra")

    # کادر BMI سمت چپ
    box_x1, box_y1 = 80, 180
    box_x2, box_y2 = 450, 480
    
    if "نرمال" in bmi_status: status_color = "#10b981" 
    elif "اضافه" in bmi_status or "چاقی" in bmi_status: status_color = "#ef4444" 
    else: status_color = "#f59e0b" 
    
    draw.rounded_rectangle([box_x1, box_y1, box_x2, box_y2], radius=30, fill=(30, 41, 59, 220), outline=status_color, width=4)
    
    draw.text(((box_x1+box_x2)//2, box_y1 + 60), _shape_text("شاخص توده بدنی (BMI)"), font=font_label, fill="#cbd5e1", anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 170), _shape_text(_format_num(bmi)), font=font_bmi, fill=status_color, anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 260), _shape_text(bmi_status), font=font_value, fill=status_color, anchor="mm")

    # خط جداکننده
    draw.line([(80, 520), (width-80, 520)], fill="#334155", width=2)

    # بخش پایین - هدف
    draw.text((width - 80, 550), _shape_text("هدف فعلی:"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 80, 590), _shape_text(goal), font=font_value, fill="#38bdf8", anchor="ra")

    # بخش پایین - نام متخصص (با استایل خاص)
    draw.text((80, 545), _shape_text("زیر نظر متخصص تغذیه:"), font=font_small, fill="#94a3b8", anchor="la")
    draw.text((80, 580), _shape_text("علی اکبر ابراهیم پور"), font=font_value, fill="#f8fafc", anchor="la")
    
    # آیدی تلگرام
    draw.text((width//2, 615), _shape_text("@AliAkbaro0"), font=font_small, fill="#64748b", anchor="mm")

    img_io = io.BytesIO()
    bg_img.convert("RGB").save(img_io, format="JPEG", quality=95)
    img_io.seek(0)
    img_io.name = 'ai_health_card.jpg'
    return img_io
