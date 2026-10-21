"""ساخت کارت‌های گرافیکی شیک برای پروفایل کاربران"""

import io
import logging
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

logger = logging.getLogger(__name__)

FONT_PATH = "Vazirmatn-Bold.ttf"

def _reshape_text(text: str) -> str:
    if not text: return ""
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)

def generate_profile_card(
    name: str, 
    age: str, 
    weight: str, 
    height: str, 
    bmi: str, 
    bmi_status: str, 
    goal: str
) -> io.BytesIO:
    """ساخت عکس کارت پروفایل"""
    
    # ابعاد کارت (مناسب استوری)
    width, height = 800, 1000
    img = Image.new("RGB", (width, height), "#1a1a2e")
    draw = ImageDraw.Draw(img)

    # ۱. کشیدن پس‌زمینه گرادیانت (تیره و شیک)
    for y in range(height):
        r = int(26 + (15 - 26) * (y / height))
        g = int(26 + (52 - 26) * (y / height))
        b = int(46 + (96 - 46) * (y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # ۲. کشیدن هدر (نوار بالایی)
    draw.rectangle([0, 0, width, 120], fill="#16213e")
    
    # بارگذاری فونت‌ها
    try:
        font_huge = ImageFont.truetype(FONT_PATH, 60)
        font_large = ImageFont.truetype(FONT_PATH, 45)
        font_med = ImageFont.truetype(FONT_PATH, 35)
        font_small = ImageFont.truetype(FONT_PATH, 25)
    except Exception:
        font_huge = font_large = font_med = font_small = ImageFont.load_default()

    # ۳. نوشتن عنوان بالای کارت
    title = _reshape_text("کارت تغذیه")
    draw.text((width//2, 60), title, font=font_large, fill="#e94560", anchor="mm")

    # ۴. نوشتن اسم کاربر
    safe_name = _reshape_text(name)
    draw.text((width//2, 180), safe_name, font=font_huge, fill="white", anchor="mm")

    # ۵. کشیدن خط جداکننده
    draw.line([(100, 230), (width-100, 230)], fill="#e94560", width=4)

    # ۶. اطلاعات (سن، قد، وزن)
    info_y = 300
    spacing = 80
    
    # سن
    age_txt = _reshape_text(f"سن: {age} سال")
    draw.text((width-100, info_y), age_txt, font=font_med, fill="#a9a9a9", anchor="ra")
    
    # قد
    height_txt = _reshape_text(f"قد: {height} سانتی‌متر")
    draw.text((width-100, info_y + spacing), height_txt, font=font_med, fill="#a9a9a9", anchor="ra")
    
    # وزن
    weight_txt = _reshape_text(f"وزن: {weight} کیلوگرم")
    draw.text((width-100, info_y + spacing*2), weight_txt, font=font_med, fill="#a9a9a9", anchor="ra")

    # ۷. کشیدن باکس BMI (وسط چپ)
    box_x1, box_y1 = 100, 280
    box_x2, box_y2 = 350, 500
    draw.rounded_rectangle([box_x1, box_y1, box_x2, box_y2], radius=20, fill="#0f3460", outline="#e94560", width=3)
    
    bmi_title = _reshape_text("شاخص BMI")
    draw.text(((box_x1+box_x2)//2, box_y1 + 50), bmi_title, font=font_small, fill="#a9a9a9", anchor="mm")
    
    bmi_val = _reshape_text(bmi)
    draw.text(((box_x1+box_x2)//2, box_y1 + 120), bmi_val, font=font_huge, fill="white", anchor="mm")
    
    bmi_stat = _reshape_text(bmi_status)
    stat_color = "#2ed573" if "نرمال" in bmi_status else "#ff4757"
    draw.text(((box_x1+box_x2)//2, box_y1 + 190), bmi_stat, font=font_med, fill=stat_color, anchor="mm")

    # ۸. کشیدن بخش هدف
    goal_y = 600
    goal_title = _reshape_text("🎯 هدف فعلی")
    draw.text((width//2, goal_y), goal_title, font=font_med, fill="#a9a9a9", anchor="mm")
    
    goal_val = _reshape_text(goal)
    draw.text((width//2, goal_y + 60), goal_val, font=font_large, fill="#e94560", anchor="mm")

    # ۹. فوتر (امضای متخصص)
    footer_y = 850
    draw.line([(100, footer_y-30), (width-100, footer_y-30)], fill="#16213e", width=2)
    
    footer_txt = _reshape_text("🥗 زیر نظر متخصص علی اکبر ابراهیم پور")
    draw.text((width//2, footer_y), footer_txt, font=font_small, fill="#a9a9a9", anchor="mm")
    
    footer_id = "@AliAkbaro0"
    draw.text((width//2, footer_y + 40), footer_id, font=font_small, fill="#e94560", anchor="mm")

    # خروجی
    img_io = io.BytesIO()
    img.save(img_io, format="JPEG", quality=95)
    img_io.seek(0)
    img_io.name = 'profile_card.jpg'
    return img_io
