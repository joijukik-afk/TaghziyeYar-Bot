import io
import os
import logging
import urllib.parse
import httpx
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)

FONT_PATH = "Vazirmatn-Bold.ttf"
FONT_URL = "https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/fonts/ttf/Vazirmatn-Bold.ttf"

# بررسی پشتیبانی از RTL در Pillow
HAS_RAQM = False
try:
    from PIL import features
    HAS_RAQM = features.check("raqm")
except ImportError:
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
    """فقط برای اعداد - بدون هیچ تغییری برمی‌گرداند"""
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

    overlay = Image.new("RGBA", bg_img.size, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(0, 0), bg_img.size], fill=(15, 23, 42, 190)) 
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
        font_num = ImageFont.truetype(FONT_PATH, 38)   
        font_label = ImageFont.truetype(FONT_PATH, 26) 
        font_bmi = ImageFont.truetype(FONT_PATH, 85)
        font_small = ImageFont.truetype(FONT_PATH, 20)
    except Exception as e:
        logger.error("فونت لود نشد: %s", e)
        return io.BytesIO()

    # تنظیمات راست‌چین (در صورت پشتیبانی)
    text_kwargs = {"direction": "rtl"} if HAS_RAQM else {}

    # ۱. هدر کارت
    draw.text((width//2, 85), "پاسپورت سلامت تغذیه‌یار", font=font_title, fill="#38bdf8", anchor="mm", **text_kwargs)
    draw.line([(300, 125), (width-300, 125)], fill="#38bdf8", width=2)
    
    # ۲. نام کاربر
    draw.text((width - 90, 160), name, font=font_name, fill="#f8fafc", anchor="ra", **text_kwargs)

    # ۳. اطلاعات (ترکیب عدد و کلمه)
    start_y = 240
    gap = 80
    
    # سن
    draw.text((width - 90, start_y), f"{_clean_num(age)} سال", font=font_num, fill="#e2e8f0", anchor="ra", **text_kwargs)
    
    # قد
    draw.text((width - 90, start_y + gap), f"{_clean_num(height)} سانتی‌متر", font=font_num, fill="#e2e8f0", anchor="ra", **text_kwargs)
    
    # وزن
    draw.text((width - 90, start_y + gap*2), f"{_clean_num(weight)} کیلوگرم", font=font_num, fill="#e2e8f0", anchor="ra", **text_kwargs)

    # ۴. کادر BMI
    box_x1, box_y1 = 80, 200
    box_x2, box_y2 = 450, 480
    
    if "نرمال" in bmi_status: status_color = "#10b981" 
    elif "اضافه" in bmi_status or "چاقی" in bmi_status: status_color = "#ef4444" 
    else: status_color = "#f59e0b" 
    
    draw.rounded_rectangle([box_x1, box_y1, box_x2, box_y2], radius=30, fill=(30, 41, 59, 240), outline=status_color, width=3)
    
    draw.text(((box_x1+box_x2)//2, box_y1 + 60), "شاخص توده بدنی (BMI)", font=font_label, fill="#cbd5e1", anchor="mm", **text_kwargs)
    draw.text(((box_x1+box_x2)//2, box_y1 + 180), _clean_num(bmi), font=font_bmi, fill=status_color, anchor="mm")
    draw.text(((box_x1+box_x2)//2, box_y1 + 260), bmi_status, font=font_num, fill=status_color, anchor="mm", **text_kwargs)

    # ۵. بخش پایین
    draw.line([(90, 500), (width-90, 500)], fill="#334155", width=2)

    # هدف
    draw.text((width - 90, 525), "هدف فعلی:", font=font_label, fill="#94a3b8", anchor="ra", **text_kwargs)
    draw.text((width - 90, 560), goal, font=font_num, fill="#38bdf8", anchor="ra", **text_kwargs)

    # متخصص
    draw.text((90, 525), "زیر نظر متخصص تغذیه:", font=font_small, fill="#94a3b8", anchor="la", **text_kwargs)
    draw.text((90, 560), "علی اکبر ابراهیم پور", font=font_num, fill="#f8fafc", anchor="la", **text_kwargs)
    
    # آیدی تلگرام
    draw.text((width//2, 610), "@AliAkbaro0", font=font_small, fill="#64748b", anchor="mm")

    img_io = io.BytesIO()
    bg_img.convert("RGB").save(img_io, format="JPEG", quality=95)
    img_io.seek(0)
    img_io.name = 'ai_health_card.jpg'
    return img_io
