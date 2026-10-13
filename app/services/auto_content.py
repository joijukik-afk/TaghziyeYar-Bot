"""تولید خودکار محتوای تغذیه‌ای با AI (Groq + browser_search) و ارسال به گروه."""

import logging
import random
from datetime import datetime, timezone

from groq import AsyncGroq

from app.config import get_settings
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)


# ============================================================
#  موضوعات برای جستجو (فارسی)
# ============================================================

SEARCH_TOPICS = [
    "آخرین یافته‌های علمی درباره تغذیه و سلامت",
    "مطالعات جدید درباره ویتامین‌ها و مواد معدنی",
    "تاثیر رژیم غذایی بر سلامت قلب و عروق",
    "نقش پروتئین و کربوهیدرات در عضله‌سازی",
    "ارتباط تغذیه با خواب و انرژی روزانه",
    "تاثیر فیبر و پروبیوتیک بر سلامت گوارش",
    "نکات جدید درباره کاهش وزن سالم",
    "اهمیت آب و هیدراتاسیون در سلامت",
    "تغذیه و سلامت روان",
    "آخرین توصیه‌های سازمان جهانی بهداشت درباره تغذیه",
    "مطالعات جدید درباره چربی‌های سالم و مضر",
    "تاثیر مصرف قند و شکر بر بدن",
    "نقش آنتی‌اکسیدان‌ها در پیشگیری از بیماری",
    "تغذیه ورزشی و عملکرد بدنی",
    "ارتباط تغذیه با سیستم ایمنی بدن",
]

# ============================================================
#  پرامپت سیستمی برای Groq
# ============================================================

SYSTEM_PROMPT = """تو یک متخصص تغذیه و سلامت هستی که برای یک گروه تلگرام فارسی محتوا تولید می‌کنی.

وظیفه تو:
1. درباره موضوع داده‌شده، با استفاده از ابزار جستجوی وب (browser_search)، آخرین اطلاعات علمی و معتبر را پیدا کن.
2. یک متن کوتاه، جذاب و کاربردی به فارسی بنویس.
3. متن باید شامل یک عنوان جذاب و یک توضیح ۳ تا ۵ خطی باشد.
4. حتماً در انتهای متن، منبع یا لینک معتبر را ذکر کن (اگر از جستجو به دست آمده).
5. از ایموجی‌های مناسب استفاده کن (زیاد نه).
6. متن باید برای اعضای گروه مفید و قابل اجرا باشد.
7. از ادعاهای قطعی و اغراق‌آمیز خودداری کن.
8. هرگز از عبارات انگلیسی در متن اصلی استفاده نکن، مگر اسم‌های علمی ضروری.

خروجی باید دقیقاً به این شکل باشد:
عنوان: [عنوان جذاب]

[متن ۳ تا ۵ خطی]

منبع: [لینک یا نام منبع]
"""

# ============================================================
#  تولید محتوا با AI
# ============================================================

async def generate_nutrition_post() -> tuple[str, str] | None:
    """تولید یک پست تغذیه‌ای جدید با AI + جستجوی وب.

    Returns:
        tuple[str, str] | None: (متن کامل, کلمه کلیدی برای جستجوی تصویر)
    """
    settings = get_settings()

    if not settings.deepseek_api_key:
        logger.warning("کلید API تنظیم نشده است.")
        return None

    topic = random.choice(SEARCH_TOPICS)

    try:
        client = AsyncGroq(api_key=settings.deepseek_api_key)

        response = await client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"موضوع: {topic}"},
            ],
            tools=[{"type": "browser_search"}],
            tool_choice="required",
            temperature=0.7,
            max_tokens=800,
        )

        content = response.choices[0].message.content
        if not content:
            logger.warning("پاسخ خالی از AI دریافت شد.")
            return None

        # استخراج کلمه کلیدی برای تصویر
        image_keyword = _extract_image_keyword(topic)

        return content.strip(), image_keyword

    except Exception as e:
        logger.warning("خطا در تولید محتوا: %s", e)
        return None


def _extract_image_keyword(topic: str) -> str:
    """استخراج کلمه کلیدی انگلیسی برای جستجوی تصویر."""
    mapping = {
        "ویتامین": "vitamins healthy food",
        "پروتئین": "protein food muscle",
        "فیبر": "fiber vegetables fruits",
        "کاهش وزن": "weight loss healthy diet",
        "آب": "water hydration drink",
        "قلب": "heart healthy food",
        "خواب": "sleep wellness food",
        "گوارش": "digestive health food",
        "قند": "sugar healthy alternatives",
        "چربی": "healthy fats avocado nuts",
        "ورزشی": "sports nutrition athlete",
        "ایمنی": "immune system fruits vegetables",
        "آنتی‌اکسیدان": "antioxidant berries",
        "سلامت روان": "mental health nutrition",
        "بهداشت": "healthy lifestyle food",
    }
    for key, value in mapping.items():
        if key in topic:
            return value
    return "healthy nutrition food"

# ============================================================
#  جستجوی تصویر با DuckDuckGo
# ============================================================

def search_food_image(keyword: str) -> str | None:
    """جستجوی یک تصویر رایگان با DuckDuckGo."""
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.images(keyword, max_results=5))
            if results:
                chosen = random.choice(results)
                return chosen.get("image")
    except Exception as e:
        logger.warning("خطا در جستجوی تصویر: %s", e)
    return None

# ============================================================
#  ارسال به گروه
# ============================================================

async def post_auto_content(bot, chat_id: int) -> bool:
    """تولید و ارسال خودکار محتوای تغذیه‌ای به گروه."""
    # ۱) تولید محتوا
    result = await generate_nutrition_post()
    if result is None:
        logger.info("محتوایی تولید نشد.")
        return False

    content, image_keyword = result

    # ۲) جستجوی تصویر
    image_url = search_food_image(image_keyword)

    # ۳) ارسال با عکس
    if image_url:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=with_signature(content),
            )
            logger.info("پست با عکس ارسال شد: %s", image_keyword)
            return True
        except Exception as e:
            logger.warning("ارسال عکس شکست خورد: %s", e)

    # ۴) ارسال فقط متن (در صورت شکست عکس)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=with_signature(content),
        )
        logger.info("پست متنی ارسال شد.")
        return True
    except Exception as e:
        logger.warning("ارسال متن شکست خورد: %s", e)
        return False
