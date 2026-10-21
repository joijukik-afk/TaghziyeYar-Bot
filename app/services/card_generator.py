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
    """این تابع فقط برای کلمات فارسی استفاده می‌شود (نه اعداد)"""
    if not text: return ""
    try:
        text = re.sub(r'[^\w\s\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF\.\!\-\+\%\(\)\/]', '', str(text))
        config = {'delete_harakat': False, 'support_ligatures': True, 'RIAL': False}
        reshaped = arabic_reshaper.reshape(text.strip(), configuration=config)
        return get_display(reshaped)
    except Exception as e:
        return str(text)

def _clean_num(val: str) -> str:
    """اعداد را به رشته صحیح تبدیل می‌کند تا Bidi آن‌ها را خراب نکند"""
    try:
        num = float(val)
        if num.is_integer(): 
            return str(int(num))
        return str(num)
    except:
        return str(val)

async def generate_ai_health_card(
    name: str, age: str, weight: str, height: str, bmi: str, bmi_status: str, goal: str
) -> io.BytesIO:
    
    await _ensure_font_exists()
    
    # پس‌زمینه‌های ساده، شیک و انتزاعی
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
            # محو کردن کامل پس‌زمینه
            bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=20))
    except Exception as e:
        logger.error(f"خطا در دریافت پس‌زمینه AI: {e}")
        bg_img = Image.new("RGBA", (1024, 640), "#0f172a")

    # لایه تاریک برای خوانایی
    overlay = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(0, 0), bg_img.size], fill=(15, 23, 42, 190)) 
    bg_img = Image.alpha_composite(bg_img, overlay)
    
    # تعریف ابعاد تصویر
    width, height = bg_img.size

    # کادر شیشه‌ای (Glassmorphism)
    glass_box = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    glass_draw = ImageDraw.Draw(glass_box)
    glass_draw.rounded_rectangle([(40, 40), (width-40, height-40)], radius=40, fill=(255, 255, 255, 15), outline=(56, 189, 248, 100), width=2)
    bg_img = Image.alpha_composite(bg_img, glass_box)
    draw = ImageDraw.Draw(bg_img)

    try:
        font_title = ImageFont.truetype(FONT_PATH, 42)
        font_name = ImageFont.truetype(FONT_PATH, 55)
        font_num = ImageFont.truetype(FONT_PATH, 38)   # فونت مخصوص اعداد
        font_label = ImageFont.truetype(FONT_PATH, 26) # فونت مخصوص کلمات
        font_bmi = ImageFont.truetype(FONT_PATH, 85)
        font_small = ImageFont.truetype(FONT_PATH, 20)
    except Exception as e:
        logger.error("فونت لود نشد: %s", e)
        return io.BytesIO()

    # ۱. هدر کارت
    draw.text((width//2, 85), _shape_text("پاسپورت سلامت تغذیه‌یار"), font=font_title, fill="#38bdf8", anchor="mm")
    draw.line([(300, 125), (width-300, 125)], fill="#38bdf8", width=2)
    
    # ۲. نام کاربر
    draw.text((width - 90, 160), _shape_text(name), font=font_name, fill="#f8fafc", anchor="ra")

    # ۳. اطلاعات (اعداد و کلمات کاملاً جدا از هم رسم می‌شوند)
    start_y = 240
    gap = 80
    
    # سن
    draw.text((width - 200, start_y), _clean_num(age), font=font_num, fill="#e2e8f0", anchor="ra")
    draw.text((width - 80, start_y), _shape_text("سال"), font=font_label, fill="#94a3b8", anchor="ra")
    
    # قد (حل قطعی مشکل 607)
    draw.text((width - 250, start_y + gap), _clean_num(height), font=font_num, fill="#e2e8f0", anchor="ra")
    draw.text((width - 80, start_y + gap), _shape_text("سانتی‌متر"), font=font_label, fill="#94a3b8", anchor="ra")
    
    # وزن
    draw.text((width - 250, start_y + gap*2), _clean_num(weight), font=font_num, fill="#e2e8f0", anchor="ra")
    draw.text((width - 80, start_y + gap*2), _shape_text("کیلوگرم"), font=font_label, fill="#94a3b8", anchor="ra")

    # ۴. کادر BMI سمت چپ
    box_x1, box_y1 = 80, 200
    box_x2, box_y2 = 450, 480
    
    if "نرمال" in bmi_status: status_color = "#10b981" 
    elif "اضافه" in bmi_status or "چاقی" in bmi_status: status_color = "#ef4444" 
    else: status_color = "#f59e0b" 
    
    draw.rounded_rectangle([box_x1, box_y1, box_x2, box_y2], radius=30, fill=(30, 41, 59, 240), outline=status_color, width=3)
    
    draw.text(((box_x1+box_x2)//2, box_y1 + 60), _shape_text("شاخص توده بدنی (BMI)"), font=font_label, fill="#cbd5e1", anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 180), _clean_num(bmi), font=font_bmi, fill=status_color, anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 260), _shape_text(bmi_status), font=font_value, fill=status_color, anchor="mm")

    # ۵. بخش پایین
    draw.line([(90, 500), (width-90, 500)], fill="#334155", width=2)

    # هدف (راست)
    draw.text((width - 90, 525), _shape_text("هدف فعلی:"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 90, 560), _shape_text(goal), font=font_num, fill="#38bdf8", anchor="ra")

    # متخصص (چپ)
    draw.text((90, 525), _shape_text("زیر نظر متخصص تغذیه:"), font=font_small, fill="#94a3b8", anchor="la")
    draw.text((90, 560), _shape_text("علی اکبر ابراهیم پور"), font=font_num, fill="#f8fafc", anchor="la")
    
    # آیدی تلگرام (وسط پایین)
    draw.text((width//2, 610), _shape_text("@AliAkbaro0"), font=font_small, fill="#64748b", anchor="mm")

    img_io = io.BytesIO()
    bg_img.convert("RGB").save(img_io, format="JPEG", quality=95)
    img_io.seek(0)
    img_io.name = 'ai_health_card.jpg'
    return img_io
