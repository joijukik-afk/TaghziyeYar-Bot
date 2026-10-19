"""سرویس تولید عکس اختصاصی برای گروه با استفاده از هوش مصنوعی"""

import logging
import urllib.parse
import random
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

async def generate_group_cover(group_name: str) -> str:
    """تولید پرامپت با هوش مصنوعی و ساخت لینک عکس"""
    
    prompt_request = (
        f"You are an expert AI art director. I have a Telegram group named: '{group_name}'.\n"
        f"Write a short, vivid, highly descriptive English image prompt (maximum 15 words) "
        f"to generate a beautiful, welcoming, high-quality cover image for this group. "
        f"If it's about health/nutrition, focus on fresh food, vibrant green colors, and a healthy lifestyle. "
        f"Make it look like a professional digital art. Only output the prompt, no extra text."
    )
    
    ai = get_ai_service()
    ai_prompt, _ = await ai.ask(user_message=prompt_request, user_id=0)
    
    # پاکسازی پرامپت از کاراکترهای اضافی
    ai_prompt = ai_prompt.strip().replace('"', '').replace("'", "").replace("\n", " ")
    logger.info("پرامپت تولید شده برای عکس گروه '%s': %s", group_name, ai_prompt)

    # ساخت آدرس عکس با سرویس رایگان Pollinations
    encoded_prompt = urllib.parse.quote(ai_prompt)
    # یک seed تصادفی اضافه می‌کنیم تا عکس هر گروه منحصر به فرد باشه
    random_seed = random.randint(1, 999999) 
    
    image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true&seed={random_seed}"
    
    return image_url
