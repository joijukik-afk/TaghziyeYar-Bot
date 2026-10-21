"""تولید کارت گرافیکی با ترکیب هوش مصنوعی (پس‌زمینه) و متن واضح فارسی"""

import io
import os
import logging
import urllib.parse
import httpx
import re
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

FONT_PATH = "Vazirmatn-Bold.ttf"
FONT_URL = "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/fonts/ttf/Vazirmatn-Bold.ttf"

# بررسی پشتیبانی از libraqm برای رندر صحیح RTL
HAS_RAQM = False
try:
    from PIL import features
    HAS_RAQM = features.check("raqm")
except Exception:
    pass
logger.info(f"Pillow Raqm Support (RTL): {HAS_RAQM}")

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
    """تبدیل مقدار به عدد صحیح (حذف اعشار) برای نمایش صحیح."""
    try:
        num = float(val)
        if num.is_integer():
            return str(int(num))
        return str(num)
    except Exception:
        return str(val)

def _render_value(draw, xy, value: str, unit: str, font_num, font_label, fill_num, fill_unit, anchor="ra"):
    """رسم اعداد و واحدها به‌صورت جداگانه برای جلوگیری از برعکس شدن ارقام."""
    x, y = xy
    # ۱. رسم واحد (سمت راست‌ترین بخش)
    if HAS_RAQM:
        draw.text((x, y), unit, font=font_label, fill=fill_unit, anchor=anchor, direction="rtl")
        # محاسبه عرض واحد برای قرار دادن عدد در سمت چپ آن
        unit_bbox = draw.textbbox((x, y), unit, font=font_label, anchor=anchor, direction="rtl")
        unit_width = unit_bbox[2] - unit_bbox[0]
    else:
        # روش جایگزین بدون Raqm (استفاده از bidi برای واحد)
        import arabic_reshaper
        from bidi.algorithm import get_display
        reshaped_unit = get_display(arabic_reshaper.reshape(unit))
        draw.text((x, y), reshaped_unit, font=font_label, fill=fill_unit, anchor=anchor)
        unit_bbox = draw.textbbox((x, y), reshaped_unit, font=font_label, anchor=anchor)
        unit_width = unit_bbox[2] - unit_bbox[0]

    # ۲. رسم عدد در سمت چپ واحد با جهت LTR
    num_x = x - unit_width - 10  # ۱۰ پیکسل فاصله بین عدد و واحد
    if HAS_RAQM:
        draw.text((num_x, y), value, font=font_num, fill=fill_num, anchor=anchor, direction="ltr")
    else:
        draw.text((num_x, y), value, font=font_num, fill=fill_num, anchor=anchor)

async def generate_ai_health_card(
    name: str, age: str, weight: str, height: str, bmi: str, bmi_status: str, goal: str
) -> io.BytesIO:
    
    await _ensure_font_exists()
    
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
            bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=20))
    except Exception as e:
        logger.error(f"خطا در دریافت پس‌زمینه AI: {e}")
        bg_img = Image.new("RGBA", (1024, 640), "#0f172a")

    # لایه تاریک برای خوانایی بهتر
    overlay = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(0, 0), bg_img.size], fill=(15, 23, 42, 190)) 
    bg_img = Image.alpha_composite(bg_img, overlay)
    
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
        font_num = ImageFont.truetype(FONT_PATH, 38)   
        font_label = ImageFont.truetype(FONT_PATH, 26) 
        font_bmi = ImageFont.truetype(FONT_PATH, 85)
        font_small = ImageFont.truetype(FONT_PATH, 20)
    except Exception as e:
        logger.error("فونت لود نشد: %s", e)
        return io.BytesIO()

    # ۱. هدر کارت
    if HAS_RAQM:
        draw.text((width//2, 85), "پاسپورت سلامت تغذیه‌یار", font=font_title, fill="#38bdf8", anchor="mm", direction="rtl")
    else:
        import arabic_reshaper
        from bidi.algorithm import get_display
        title_text = get_display(arabic_reshaper.reshape("پاسپورت سلامت تغذیه‌یار"))
        draw.text((width//2, 85), title_text, font=font_title, fill="#38bdf8", anchor="mm")
    
    draw.line([(300, 125), (width-300, 125)], fill="#38bdf8", width=2)
    
    # ۲. نام کاربر
    if HAS_RAQM:
        draw.text((width - 90, 160), name, font=font_name, fill="#f8fafc", anchor="ra", direction="rtl")
    else:
        name_text = get_display(arabic_reshaper.reshape(name))
        draw.text((width - 90, 160), name_text, font=font_name, fill="#f8fafc", anchor="ra")

    # ۳. اطلاعات (استفاده از تابع کمکی برای جداسازی عدد و واحد)
    start_y = 240
    gap = 80
    
    # سن
    _render_value(draw, (width - 90, start_y), _clean_num(age), "سال", font_num, font_label, "#e2e8f0", "#94a3b8")
    
    # قد (حل قطعی مشکل 607)
    _render_value(draw, (width - 90, start_y + gap), _clean_num(height), "سانتی‌متر", font_num, font_label, "#e2e8f0", "#94a3b8")
    
    # وزن
    _render_value(draw, (width - 90, start_y + gap*2), _clean_num(weight), "کیلوگرم", font_num, font_label, "#e2e8f0", "#94a3b8")

    # ۴. کادر BMI
    box_x1, box_y1 = 80, 200
    box_x2, box_y2 = 450, 480
    
    if "نرمال" in bmi_status: status_color = "#10b981" 
    elif "اضافه" in bmi_status or "چاقی" in bmi_status: status_color = "#ef4444" 
    else: status_color = "#f59e0b" 
    
    draw.rounded_rectangle([box_x1, box_y1, box_x2, box_y2], radius=30, fill=(30, 41, 59, 240), outline=status_color, width=3)
    
    # متن "شاخص توده بدنی (BMI)"
    if HAS_RAQM:
        draw.text(((box_x1+box_x2)//2, box_y1 + 60), "شاخص توده بدنی (BMI)", font=font_label, fill="#cbd5e1", anchor="mm", direction="rtl")
    else:
        bmi_title = get_display(arabic_reshaper.reshape("شاخص توده بدنی (BMI)"))
        draw.text(((box_x1+box_x2)//2, box_y1 + 60), bmi_title, font=font_label, fill="#cbd5e1", anchor="mm")

    # عدد BMI (فقط عدد، بدون واحد)
    draw.text(((box_x1+box_x2)//2, box_y1 + 180), _clean_num(bmi), font=font_bmi, fill=status_color, anchor="mm")

    # وضعیت BMI (نرمال، اضافه وزن و...)
    if HAS_RAQM:
        draw.text(((box_x1+box_x2)//2, box_y1 + 260), bmi_status, font=font_num, fill=status_color, anchor="mm", direction="rtl")
    else:
        bmi_status_text = get_display(arabic_reshaper.reshape(bmi_status))
        draw.text(((box_x1+box_x2)//2, box_y1 + 260), bmi_status_text, font=font_num, fill=status_color, anchor="mm")

    # ۵. بخش پایین
    draw.line([(90, 500), (width-90, 500)], fill="#334155", width=2)

    # هدف فعلی
    if HAS_RAQM:
        draw.text((width - 90, 525), "هدف فعلی:", font=font_label, fill="#94a3b8", anchor="ra", direction="rtl")
        draw.text((width - 90, 560), goal, font=font_num, fill="#38bdf8", anchor="ra", direction="rtl")
    else:
        goal_title = get_display(arabic_reshaper.reshape("هدف فعلی:"))
        draw.text((width - 90, 525), goal_title, font=font_label, fill="#94a3b8", anchor="ra")
        goal_text = get_display(arabic_reshaper.reshape(goal))
        draw.text((width - 90, 560), goal_text, font=font_num, fill="#38bdf8", anchor="ra")

    # نام متخصص
    if HAS_RAQM:
        draw.text((90, 525), "زیر نظر متخصص تغذیه:", font=font_small, fill="#94a3b8", anchor="la", direction="rtl")
        draw.text((90, 560), "علی اکبر ابراهیم پور", font=font_num, fill="#f8fafc", anchor="la", direction="rtl")
    else:
        expert_title = get_display(arabic_reshaper.reshape("زیر نظر متخصص تغذیه:"))
        draw.text((90, 525), expert_title, font=font_small, fill="#94a3b8", anchor="la")
        expert_name = get_display(arabic_reshaper.reshape("علی اکبر ابراهیم پور"))
        draw.text((90, 560), expert_name, font=font_num, fill="#f8fafc", anchor="la")
    
    # آیدی تلگرام
    draw.text((width//2, 610), "@AliAkbaro0", font=font_small, fill="#64748b", anchor="mm")

    img_io = io.BytesIO()
    bg_img.convert("RGB").save(img_io, format="JPEG", quality=95)
    img_io.seek(0)
    img_io.name = 'ai_health_card.jpg'
    return img_io
