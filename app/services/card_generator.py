"""ساخت کارت گرافیکی فوق حرفه‌ای (پاسپورت سلامت)"""

import io
import os
import logging
import random
import httpx
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

logger = logging.getLogger(__name__)

FONT_PATH = "Vazirmatn-Bold.ttf"
FONT_URL = "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Bold.ttf"

async def _ensure_font_exists():
    """اطمینان از وجود فونت فارسی روی سرور Render"""
    if not os.path.exists(FONT_PATH):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(FONT_URL, follow_redirects=True)
                if resp.status_code == 200:
                    with open(FONT_PATH, "wb") as f:
                        f.write(resp.content)
        except Exception as e:
            logger.warning("خطا در دانلود فونت کارت: %s", e)

def _shape_text(text: str) -> str:
    """آماده‌سازی متن فارسی برای رندر صحیح در Pillow"""
    if not text: return ""
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)

async def generate_profile_card(
    name: str, age: str, weight: str, height: str, bmi: str, bmi_status: str, goal: str
) -> io.BytesIO:
    
    await _ensure_font_exists()
    
    # ابعاد کارت
    width, height = 1024, 640
    radius = 35
    
    # ۱. پس‌زمینه گرادیانت
    img = Image.new("RGBA", (width, height), "#0f172a")
    draw = ImageDraw.Draw(img)
    for y in range(height):
        r = int(15 + (10 - 15) * (y / height))
        g = int(23 + (25 - 23) * (y / height))
        b = int(42 + (47 - 42) * (y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # ۲. بارگذاری فونت‌ها
    try:
        font_title = ImageFont.truetype(FONT_PATH, 28)
        font_name = ImageFont.truetype(FONT_PATH, 60)
        font_value = ImageFont.truetype(FONT_PATH, 38)
        font_label = ImageFont.truetype(FONT_PATH, 24)
        font_small = ImageFont.truetype(FONT_PATH, 20)
        font_bmi = ImageFont.truetype(FONT_PATH, 80)
    except Exception as e:
        logger.error("فونت لود نشد: %s", e)
        return io.BytesIO() 

    # ۳. هدر بالای کارت
    draw.rectangle([(0, 0), (width, 90)], fill="#1e293b")
    draw.text((width//2, 45), _shape_text("🌱 پاسپورت سلامت تغذیه‌یار"), font=font_title, fill="#38bdf8", anchor="mm")

    # ۴. نام کاربر
    draw.text((width - 60, 140), _shape_text(name), font=font_name, fill="#f8fafc", anchor="ra")

    # ۵. اطلاعات شخصی
    start_y = 260
    gap = 75
    
    draw.text((width - 60, start_y), _shape_text("سن"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 200, start_y), _shape_text(f"{age} سال"), font=font_value, fill="#e2e8f0", anchor="ra")
    
    draw.text((width - 60, start_y + gap), _shape_text("قد"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 200, start_y + gap), _shape_text(f"{height} cm"), font=font_value, fill="#e2e8f0", anchor="ra")
    
    draw.text((width - 60, start_y + gap*2), _shape_text("وزن"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 200, start_y + gap*2), _shape_text(f"{weight} kg"), font=font_value, fill="#e2e8f0", anchor="ra")

    # ۶. باکس BMI
    box_x1, box_y1 = 60, 180
    box_x2, box_y2 = 450, 480
    
    if "نرمال" in bmi_status: status_color = "#10b981"
    elif "اضافه" in bmi_status or "چاقی" in bmi_status: status_color = "#ef4444"
    else: status_color = "#f59e0b"
    
    draw.rounded_rectangle([box_x1, box_y1, box_x2, box_y2], radius=30, fill="#1e293b", outline=status_color, width=4)
    
    draw.text(((box_x1+box_x2)//2, box_y1 + 60), _shape_text("شاخص توده بدنی (BMI)"), font=font_label, fill="#cbd5e1", anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 170), _shape_text(bmi), font=font_bmi, fill=status_color, anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 250), _shape_text(bmi_status), font=font_value, fill=status_color, anchor="mm")

    # ۷. خط جداکننده
    draw.line([(60, 520), (width-60, 520)], fill="#334155", width=2)

    # ۸. هدف
    draw.text((width - 60, 560), _shape_text("🎯 هدف فعلی"), font=font_small, fill="#94a3b8", anchor="ra")
    draw.text((width - 60, 600), _shape_text(goal), font=font_value, fill="#38bdf8", anchor="ra")

    # ۹. امضا
    draw.text((60, 555), _shape_text("زیر نظر متخصص:"), font=font_small, fill="#94a3b8", anchor="la")
    draw.text((60, 590), _shape_text("علی اکبر ابراهیم پور"), font=font_value, fill="#f8fafc", anchor="la")
    
    # ۱۰. بارکد تزئینی
    bar_x = width - 60
    bar_y = 540
    for _ in range(15):
        w = random.choice([2, 3, 4])
        h = random.choice([15, 25, 30])
        draw.rectangle([bar_x, bar_y, bar_x - w, bar_y + h], fill="#475569")
        bar_x -= (w + 3)

    # ۱۱. گرد کردن گوشه‌ها
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (width, height)], radius=radius, fill=255)
    
    output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    output.paste(img, (0, 0), mask)
    
    final_img = Image.new("RGB", (width, height), "#0f172a")
    final_img.paste(output, (0, 0), output)
    
    img_io = io.BytesIO()
    final_img.save(img_io, format="JPEG", quality=95)
    img_io.seek(0)
    img_io.name = 'health_passport.jpg'
    return img_io
