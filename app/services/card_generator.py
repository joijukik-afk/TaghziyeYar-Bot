"""ساخت کارت گرافیکی فوق حرفه‌ای (Digital ID) برای کاربران"""

import io
import os
import logging
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import arabic_reshaper
from bidi.algorithm import get_display

logger = logging.getLogger(__name__)

FONT_PATH = "Vazirmatn-Bold.ttf"

def _shape_text(text: str) -> str:
    if not text: return ""
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)

def _draw_rounded_rect_with_glow(img, xy, radius, color, glow_color):
    """کشیدن مستطیل با گوشه گرد و افکت درخشش"""
    # لایه شفاف برای افکت درخشش
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    
    # رسم مستطیل بزرگتر برای درخشش
    x1, y1, x2, y2 = xy
    glow_draw.rounded_rectangle([x1-5, y1-5, x2+5, y2+5], radius=radius+5, fill=glow_color)
    glow = glow.filter(ImageFilter.GaussianBlur(15))
    img.alpha_composite(glow)
    
    # رسم مستطیل اصلی
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(xy, radius=radius, fill=color)

def generate_profile_card(
    name: str, age: str, weight: str, height: str, bmi: str, bmi_status: str, goal: str
) -> io.BytesIO:
    
    # ابعاد کارت (مثل کارت شناسایی)
    width, height = 1000, 600
    radius = 40
    
    # ۱. ساخت پس‌زمینه گرادیانت تیره و شیک
    img = Image.new("RGBA", (width, height), "#0f172a")
    draw = ImageDraw.Draw(img)
    for y in range(height):
        r = int(15 + (30 - 15) * (y / height))
        g = int(23 + (41 - 23) * (y / height))
        b = int(42 + (59 - 42) * (y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # ۲. بارگذاری فونت‌ها
    try:
        font_title = ImageFont.truetype(FONT_PATH, 40)
        font_name = ImageFont.truetype(FONT_PATH, 65)
        font_value = ImageFont.truetype(FONT_PATH, 45)
        font_label = ImageFont.truetype(FONT_PATH, 25)
        font_small = ImageFont.truetype(FONT_PATH, 20)
        font_bmi_val = ImageFont.truetype(FONT_PATH, 80)
    except Exception:
        logger.warning("فونت وزیرمتن یافت نشد، از فونت پیش‌فرض استفاده می‌شود.")
        font_title = font_name = font_value = font_label = font_small = font_bmi_val = ImageFont.load_default()

    # ۳. کشیدن هدر بالای کارت
    draw.rectangle([(0, 0), (width, 80)], fill="#1e293b")
    title = _shape_text("کارت دیجیتال تغذیه")
    draw.text((width//2, 40), title, font=font_title, fill="#38bdf8", anchor="mm")

    # ۴. نام کاربر
    safe_name = _shape_text(name)
    draw.text((width - 80, 160), safe_name, font=font_name, fill="#f8fafc", anchor="ra")
    
    # ۵. اطلاعات شخصی (سمت راست)
    # سن
    draw.text((width - 80, 260), _shape_text("سن"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 180, 260), _shape_text(f"{age} سال"), font=font_value, fill="#e2e8f0", anchor="ra")
    
    # قد
    draw.text((width - 80, 340), _shape_text("قد"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 180, 340), _shape_text(f"{height} سانتی‌متر"), font=font_value, fill="#e2e8f0", anchor="ra")
    
    # وزن
    draw.text((width - 80, 420), _shape_text("وزن"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 180, 420), _shape_text(f"{weight} کیلوگرم"), font=font_value, fill="#e2e8f0", anchor="ra")

    # ۶. باکس BMI (سمت چپ) با افکت شیشه‌ای
    bmi_box_x1, bmi_box_y1 = 80, 180
    bmi_box_x2, bmi_box_y2 = 420, 460
    
    # رنگ بر اساس وضعیت
    if "نرمال" in bmi_status: status_color = "#10b981" # سبز
    elif "اضافه" in bmi_status or "چاقی" in bmi_status: status_color = "#ef4444" # قرمز
    else: status_color = "#f59e0b" # نارنجی
    
    # رسم باکس شیشه‌ای
    _draw_rounded_rect_with_glow(img, [bmi_box_x1, bmi_box_y1, bmi_box_x2, bmi_box_y2], 30, (30, 41, 59, 200), status_color + "40")
    
    # نوشتن داخل باکس BMI
    draw.text(((bmi_box_x1+bmi_box_x2)//2, bmi_box_y1 + 50), _shape_text("شاخص توده بدنی (BMI)"), font=font_label, fill="#cbd5e1", anchor="mm")
    draw.text(((bmi_box_x1+bmi_box_x2)//2, bmi_box_y1 + 140), _shape_text(bmi), font=font_bmi_val, fill=status_color, anchor="mm")
    draw.text(((bmi_box_x1+bmi_box_x2)//2, bmi_box_y1 + 230), _shape_text(bmi_status), font=font_value, fill=status_color, anchor="mm")

    # ۷. هدف (پایین سمت راست)
    draw.text((width - 80, 500), _shape_text("🎯 هدف فعلی"), font=font_label, fill="#94a3b8", anchor="ra")
    draw.text((width - 80, 550), _shape_text(goal), font=font_value, fill="#38bdf8", anchor="ra")

    # ۸. امضا (پایین سمت چپ)
    draw.text((80, 520), _shape_text("زیر نظر متخصص:"), font=font_small, fill="#94a3b8", anchor="la")
    draw.text((80, 550), _shape_text("علی اکبر ابراهیم پور"), font=font_value, fill="#f8fafc", anchor="la")
    draw.text((80, 585), "@AliAkbaro0", font=font_small, fill="#38bdf8", anchor="la")

    # ۹. خط جداکننده
    draw.line([(500, 100), (500, 500)], fill="#334155", width=2)

    # ۱۰. گرد کردن گوشه‌های کل عکس
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (width, height)], radius=radius, fill=255)
    
    output = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    output.paste(img, (0, 0), mask)
    
    # خروجی به صورت JPEG (برای کاهش حجم)
    final_img = Image.new("RGB", (width, height), "#0f172a")
    final_img.paste(output, (0, 0), output)
    
    img_io = io.BytesIO()
    final_img.save(img_io, format="JPEG", quality=95)
    img_io.seek(0)
    img_io.name = 'digital_id_card.jpg'
    return img_io
