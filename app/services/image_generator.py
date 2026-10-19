"""سرویس تولید عکس اختصاصی و شیک برای گروه"""

import io
import logging
import random
import urllib.parse
import os
import httpx
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

from app.services.ai_service import get_ai_service
from app.config import get_settings

logger = logging.getLogger(__name__)

FONT_PATH = "Vazirmatn-Bold.ttf"
FONT_URL = "https://github.com/rastikerdar/vazirmatn/raw/master/fonts/ttf/Vazirmatn-Bold.ttf"

async def _ensure_font_exists():
    """اطمینان از وجود فونت زیبای فارسی"""
    if not os.path.exists(FONT_PATH):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(FONT_URL, follow_redirects=True)
                if resp.status_code == 200:
                    with open(FONT_PATH, "wb") as f:
                        f.write(resp.content)
        except Exception as e:
            logger.warning("خطا در دانلود فونت: %s", e)

def _reshape_persian_text(text: str) -> str:
    """آماده‌سازی متن فارسی برای نوشتن روی عکس (راست‌چین)"""
    reshaped_text = arabic_reshaper.reshape(text)
    return get_display(reshaped_text)

async def generate_group_cover(group_name: str) -> io.BytesIO:
    """تولید پرامپت با هوش مصنوعی، ساخت عکس و نوشتن متن زیبا روی آن"""
    
    await _ensure_font_exists()

    # ۱. هوش مصنوعی یک پرامپت هنری فوق‌العاده برای پس‌زمینه می‌سازد
    prompt_request = (
        f"You are an expert AI art director. I need a background image for a Telegram group about Nutrition and Health. "
        f"Generate a highly detailed, vivid English prompt for a 3D claymorphism or Pixar-style illustration. "
        f"The image MUST feature delicious, fresh, healthy food (fruits, vegetables, nuts) in a beautiful composition. "
        f"Colors should be vibrant green, orange, and warm tones. "
        f"IMPORTANT: Leave empty space in the center of the image for text. "
        f"Do NOT include any text in the prompt. Just the visual description."
    )
    
    ai = get_ai_service()
    ai_prompt, _ = await ai.ask(user_message=prompt_request, user_id=0)
    
    # پاکسازی پرامپت
    ai_prompt = ai_prompt.strip().replace('"', '').replace("'", "").replace("\n", " ")
    logger.info("پرامپت تولید شده برای پس‌زمینه گروه '%s': %s", group_name, ai_prompt)

    # ۲. ساخت عکس با سرویس Pollinations
    encoded_prompt = urllib.parse.quote(ai_prompt)
    random_seed = random.randint(1, 999999) 
    
    settings = get_settings()
    api_key = getattr(settings, 'pollinations_api_key', '')

    if api_key:
        image_url = (
            f"https://gen.pollinations.ai/image/{encoded_prompt}"
            f"?width=1024&height=1024&nologo=true&seed={random_seed}&model=flux&key={api_key}"
        )
        logger.info("استفاده از مدل Flux برای تولید عکس...")
    else:
        image_url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?width=1024&height=1024&nologo=true&seed={random_seed}"
        )
        logger.warning("توکن Pollinations تنظیم نشده. استفاده از مدل پیش‌فرض...")

    # ۳. دانلود عکس
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.get(image_url)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGBA")

    # ۴. آماده‌سازی متن‌ها برای نوشتن روی عکس
    text_title = _reshape_persian_text("تغذیه گروه")
    text_group = _reshape_persian_text(group_name)

    # ۵. نوشتن متن روی عکس با استایل شیک
    try:
        font_title = ImageFont.truetype(FONT_PATH, 80)
        font_group = ImageFont.truetype(FONT_PATH, 110)
    except Exception:
        font_title = ImageFont.load_default()
        font_group = ImageFont.load_default()

    width, height = img.size
    
    # یک باکس نیمه‌شفاف مشکی در وسط عکس برای خوانایی بیشتر متن
    overlay = Image.new('RGBA', img.size, (0,0,0,0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle([(0, height//2 - 200), (width, height//2 + 200)], fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # گرفتن اندازه متن برای وسط‌چین کردن
    bbox_title = draw.textbbox((0, 0), text_title, font=font_title)
    bbox_group = draw.textbbox((0, 0), text_group, font=font_group)
    
    w_title, h_title = bbox_title[2] - bbox_title[0], bbox_title[3] - bbox_title[1]
    w_group, h_group = bbox_group[2] - bbox_group[0], bbox_group[3] - bbox_group[1]
    
    # مختصات نوشتن
    x_title = (width - w_title) / 2
    y_title = (height / 2) - h_title - 50
    
    x_group = (width - w_group) / 2
    y_group = (height / 2) + 10

    # سایه و متن اصلی
    draw.text((x_title+3, y_title+3), text_title, font=font_title, fill=(0, 0, 0, 200))
    draw.text((x_title, y_title), text_title, font=font_title, fill=(255, 215, 0, 255)) # رنگ طلایی
    
    draw.text((x_group+3, y_group+3), text_group, font=font_group, fill=(0, 0, 0, 200))
    draw.text((x_group, y_group), text_group, font=font_group, fill=(255, 255, 255, 255)) # رنگ سفید

    # ۶. خروجی گرفتن به صورت BytesIO
    final_image_io = io.BytesIO()
    img.convert("RGB").save(final_image_io, format="JPEG", quality=95)
    final_image_io.seek(0)
    final_image_io.name = 'cover.jpg'
    
    return final_image_io
