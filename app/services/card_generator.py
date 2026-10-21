"""تولید کارت گرافیکی با ترکیب هوش مصنوعی (پس‌زمینه) و متن واضح فارسی"""

import io
import os
import logging
import urllib.parse
import httpx
import re
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
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
    """تبدیل عدد به رشته با دستور LTR برای جلوگیری از برعکس شدن (607)"""
    try:
        num = float(val)
        if num.is_integer(): 
            # \u202A (LTR) و \u202C (Pop Directional Formatting)
            return f"\u202A{int(num)}\u202C"
        return f"\u202A{num}\u202C"
    except:
        return f"\u202A{val}\u202C"

async def generate_ai_health_card(
    name: str, age: str, weight: str, height: str, bmi: str, bmi_status: str, goal: str
) -> io.BytesIO:
    
    await _ensure_font_exists()
    
    # پرامپت بسیار ساده برای اینکه هوش مصنوعی فقط رنگ و گرادیانت بسازه، نه آدمک و کارت!
    prompts = [
        "Abstract dark blue and teal gradient background, smooth glowing waves, professional, minimalistic, no text, no people, no objects, no faces, high resolution.",
        "Abstract dark emerald green and gold gradient background, smooth glowing curves, professional, minimalistic, no text, no people, no objects, high resolution.",
        "Abstract dark purple and cyan gradient background, smooth glowing lines, professional, minimalistic, no text, no people, no objects, high resolution.",
        "Abstract dark slate and neon blue gradient background, smooth glowing particles, professional, minimalistic, no text, no people, no objects, high resolution."
    ]
    prompt = random.choice(prompts)
    
    encoded_prompt = urllib.parse.quote(prompt)
    ai_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=640&nologo=true&model=flux"
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(ai_url)
            resp.raise_for_status()
            bg_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            
            # 👇 بلور (محو) کردن پس‌زمینه تا هرگونه جزئیات مزاحم از بین برود
            bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=15))
    except Exception as e:
        logger.error(f"خطا در دریافت پس‌زمینه AI: {e}")
        bg_img = Image.new("RGBA", (1024, 640), "#0f172a")

    # لایه تاریک برای خوانایی بهتر
    overlay = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(0, 0), bg_img.size], fill=(15, 23, 42, 200)) 
    bg_img = Image.alpha_composite(bg_img, overlay)
    draw = ImageDraw.Draw(bg_img)

    # 👇 رسم کادر شیشه‌ای (Glassmorphism) برای زیبایی و ست شدن
    glass_box = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    glass_draw = ImageDraw.Draw(glass_box)
    glass_draw.rounded_rectangle([(40, 40), (width-40, height-40)], radius=40, fill=(255, 255, 255, 20), outline=(255, 255, 255, 60), width=2)
    bg_img = Image.alpha_composite(bg_img, glass_box)
    draw = ImageDraw.Draw(bg_img)

    try:
        font_title = ImageFont.truetype(FONT_PATH, 42)
        font_name = ImageFont.truetype(FONT_PATH, 60)
        font_value = ImageFont.truetype(FONT_PATH, 38)
        font_unit = ImageFont.truetype(FONT_PATH, 24)
        font_label = ImageFont.truetype(FONT_PATH, 26)
        font_bmi = ImageFont.truetype(FONT_PATH, 85)
        font_small = ImageFont.truetype(FONT_PATH, 22)
    except Exception as e:
        logger.error("فونت لود نشد: %s", e)
        return io.BytesIO()

    width, height = bg_img.size

    # ۱. هدر کارت
    draw.text((width//2, 90), _shape_text("پاسپورت سلامت تغذیه‌یار"), font=font_title, fill="#38bdf8", anchor="mm")
    draw.line([(250, 130), (width-250, 130)], fill="#38bdf8", width=2)
    
    # ۲. نام کاربر
    draw.text((width - 90, 180), _shape_text(name), font=font_name, fill="#f8fafc", anchor="ra")

    # ۳. اطلاعات (اعداد با _format_num و کلمات با _shape_text)
    start_y = 260
    gap = 80
    
    # سن
    draw.text((width - 90, start_y), _shape_text("سن"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 150, start_y), _shape_text("سال"), font=font_unit, fill="#94a3b8", anchor="ra")
    draw.text((width - 210, start_y - 5), _format_num(age), font=font_value, fill="#e2e8f0", anchor="ra")
    
    # قد
    draw.text((width - 90, start_y + gap), _shape_text("قد"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 150, start_y + gap), _shape_text("سانتی‌متر"), font=font_unit, fill="#94a3b8", anchor="ra")
    draw.text((width - 280, start_y + gap - 5), _format_num(height), font=font_value, fill="#e2e8f0", anchor="ra")
    
    # وزن
    draw.text((width - 90, start_y + gap*2), _shape_text("وزن"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 150, start_y + gap*2), _shape_text("کیلوگرم"), font=font_unit, fill="#94a3b8", anchor="ra")
    draw.text((width - 290, start_y + gap*2 - 5), _format_num(weight), font=font_value, fill="#e2e8f0", anchor="ra")

    # ۴. کادر BMI سمت چپ
    box_x1, box_y1 = 90, 200
    box_x2, box_y2 = 440, 480
    
    if "نرمال" in bmi_status: status_color = "#10b981" 
    elif "اضافه" in bmi_status or "چاقی" in bmi_status: status_color = "#ef4444" 
    else: status_color = "#f59e0b" 
    
    draw.rounded_rectangle([box_x1, box_y1, box_x2, box_y2], radius=30, fill=(30, 41, 59, 220), outline=status_color, width=4)
    
    draw.text(((box_x1+box_x2)//2, box_y1 + 60), _shape_text("شاخص توده بدنی (BMI)"), font=font_label, fill="#cbd5e1", anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 180), _format_num(bmi), font=font_bmi, fill=status_color, anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 260), _shape_text(bmi_status), font=font_value, fill=status_color, anchor="mm")

    # ۵. بخش پایین (هدف و متخصص)
    draw.line([(90, 510), (width-90, 510)], fill="#334155", width=2)

    # هدف (راست)
    draw.text((width - 90, 540), _shape_text("هدف فعلی:"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 90, 580), _shape_text(goal), font=font_value, fill="#38bdf8", anchor="ra")

    # متخصص (چپ)
    draw.text((90, 540), _shape_text("زیر نظر متخصص تغذیه:"), font=font_small, fill="#94a3b8", anchor="la")
    draw.text((90, 575), _shape_text("علی اکبر ابراهیم پور"), font=font_value, fill="#f8fafc", anchor="la")
    
    # ۶. آیدی تلگرام (وسط پایین)
    draw.text((width//2, 620), _shape_text("@AliAkbaro0"), font=font_small, fill="#64748b", anchor="mm")

    img_io = io.BytesIO()
    bg_img.convert("RGB").save(img_io, format="JPEG", quality=95)
    img_io.seek(0)
    img_io.name = 'ai_health_card.jpg'
    return img_io
