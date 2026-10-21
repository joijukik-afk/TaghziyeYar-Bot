"""تولید کارت گرافیکی با ترکیب هوش مصنوعی (پس‌زمینه) و متن واضح فارسی"""

import io
import os
import logging
import urllib.parse
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

def _shape_text(text: str) -> str:
    if not text: return ""
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)

async def generate_ai_health_card(
    name: str, age: str, weight: str, height: str, bmi: str, bmi_status: str, goal: str
) -> io.BytesIO:
    
    await _ensure_font_exists()
    
    # ۱. دریافت پس‌زمینه شیک از هوش مصنوعی
    prompt = (
        "A highly professional, modern, dark-themed digital ID card template background. "
        "Dark blue gradient with glassmorphism, glowing neon blue accents. "
        "Blank empty space in the center for text. High resolution, 8k, clean UI design. "
        "No text, no letters, no words, no watermarks."
    )
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

    # ۲. آماده‌سازی تصویر
    overlay = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(0, 0), bg_img.size], fill=(15, 23, 42, 150)) 
    bg_img = Image.alpha_composite(bg_img, overlay)
    draw = ImageDraw.Draw(bg_img)

    try:
        font_title = ImageFont.truetype(FONT_PATH, 40)
        font_name = ImageFont.truetype(FONT_PATH, 65)
        font_value = ImageFont.truetype(FONT_PATH, 40)
        font_label = ImageFont.truetype(FONT_PATH, 25)
        font_bmi = ImageFont.truetype(FONT_PATH, 85)
        font_small = ImageFont.truetype(FONT_PATH, 20)
    except Exception as e:
        logger.error("فونت لود نشد: %s", e)
        return io.BytesIO()

    width, height = bg_img.size

    draw.text((width//2, 50), _shape_text("🌱 پاسپورت سلامت تغذیه‌یار"), font=font_title, fill="#38bdf8", anchor="mm")
    draw.text((width - 80, 150), _shape_text(name), font=font_name, fill="#f8fafc", anchor="ra")

    start_y = 260
    gap = 80
    draw.text((width - 80, start_y), _shape_text("سن"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 220, start_y), _shape_text(f"{age} سال"), font=font_value, fill="#e2e8f0", anchor="ra")
    
    draw.text((width - 80, start_y + gap), _shape_text("قد"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 220, start_y + gap), _shape_text(f"{height} cm"), font=font_value, fill="#e2e8f0", anchor="ra")
    
    draw.text((width - 80, start_y + gap*2), _shape_text("وزن"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 220, start_y + gap*2), _shape_text(f"{weight} kg"), font=font_value, fill="#e2e8f0", anchor="ra")

    box_x1, box_y1 = 80, 180
    box_x2, box_y2 = 450, 480
    
    if "نرمال" in bmi_status: status_color = "#10b981" 
    elif "اضافه" in bmi_status or "چاقی" in bmi_status: status_color = "#ef4444" 
    else: status_color = "#f59e0b" 
    
    draw.rounded_rectangle([box_x1, box_y1, box_x2, box_y2], radius=30, fill=(30, 41, 59, 200), outline=status_color, width=4)
    
    draw.text(((box_x1+box_x2)//2, box_y1 + 60), _shape_text("شاخص توده بدنی (BMI)"), font=font_label, fill="#cbd5e1", anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 170), _shape_text(bmi), font=font_bmi, fill=status_color, anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 250), _shape_text(bmi_status), font=font_value, fill=status_color, anchor="mm")

    draw.line([(80, 520), (width-80, 520)], fill="#334155", width=2)

    draw.text((width - 80, 560), _shape_text("🎯 هدف فعلی"), font=font_small, fill="#94a3b8", anchor="ra")
    draw.text((width - 80, 600), _shape_text(goal), font=font_value, fill="#38bdf8", anchor="ra")

    draw.text((80, 555), _shape_text("زیر نظر متخصص:"), font=font_small, fill="#94a3b8", anchor="la")
    draw.text((80, 595), _shape_text("علی اکبر ابراهیم پور"), font=font_value, fill="#f8fafc", anchor="la")
    
    draw.text((width//2, 610), _shape_text("@AliAkbaro0"), font=font_small, fill="#64748b", anchor="mm")

    img_io = io.BytesIO()
    bg_img.convert("RGB").save(img_io, format="JPEG", quality=95)
    img_io.seek(0)
    img_io.name = 'ai_health_card.jpg'
    return img_io
