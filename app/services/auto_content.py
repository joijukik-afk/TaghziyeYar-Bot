"""تولید و ارسال خودکار محتوای تغذیه‌ای به همه گروه‌ها."""

import logging
import random

from groq import AsyncGroq

from app.config import get_settings
from app.database import repository as repo
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)


# ============================================================
#  موضوعات
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
    "نقش ویتامین D در سلامت استخوان و ایمنی",
    "چطور فیبر بیشتر از غذا دریافت کنیم",
    "میان‌وعده‌های سالم برای محل کار",
    "تاثیر رژیم مدیترانه‌ای بر سلامت",
    "راهکارهای کاهش مصرف نمک و شکر",
]


SYSTEM_PROMPT = """تو یک متخصص تغذیه و سلامت هستی که برای یک گروه تلگرام فارسی محتوا تولید می‌کنی.

وظیفه تو:
1. با استفاده از ابزار جستجوی وب، آخرین اطلاعات علمی و معتبر را پیدا کن.
2. یک متن کوتاه، جذاب و کاربردی به فارسی بنویس.
3. متن شامل یک عنوان جذاب و توضیح ۳ تا ۵ خطی باشد.
4. حتماً در انتها منبع یا لینک معتبر را ذکر کن.
5. از ایموجی‌های مناسب استفاده کن (زیاد نه).
6. متن باید مفید و قابل اجرا باشد.
7. از ادعاهای قطعی و اغراق‌آمیز خودداری کن.
8. هرگز از عبارات انگلیسی در متن اصلی استفاده نکن.

ساختار:
عنوان: [عنوان]

[متن ۳ تا ۵ خطی]

منبع: [لینک یا نام منبع]
"""


# ============================================================
#  تولید محتوا
# ============================================================

async def generate_nutrition_post() -> tuple[str, str] | None:
    """تولید پست جدید. Returns (text, image_keyword) یا None."""
    settings = get_settings()

    if not settings.deepseek_api_key:
        logger.warning("کلید API تنظیم نشده.")
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
            tool_choice="auto",
            temperature=0.7,
            max_tokens=800,
        )

        content = response.choices[0].message.content
        if not content:
            logger.warning("پاسخ خالی از AI.")
            return None

        image_keyword = _extract_image_keyword(topic)
        return content.strip(), image_keyword

    except Exception as e:
        logger.warning("خطا در تولید: %s", e)
        return None


def _extract_image_keyword(topic: str) -> str:
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
        "مدیترانه": "mediterranean diet food",
        "نمک": "low sodium healthy food",
        "میان‌وعده": "healthy snack",
        "استخوان": "bone health dairy",
        "پروبیوتیک": "probiotic yogurt",
    }
    for key, value in mapping.items():
        if key in topic:
            return value
    return "healthy nutrition food"


# ============================================================
#  جستجوی تصویر
# ============================================================

def search_food_image(keyword: str) -> str | None:
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(keyword, max_results=5))
            if results:
                chosen = random.choice(results)
                url = chosen.get("image")
                if url and url.startswith("http"):
                    return url
    except Exception as e:
        logger.warning("جستجوی تصویر خطا داد: %s", e)
    return None


# ============================================================
#  ارسال به همه گروه‌ها
# ============================================================

async def broadcast_auto_content(bot) -> int:
    """تولید محتوا و ارسال به همه گروه‌های ثبت‌شده."""
    try:
        groups = await repo.list_all_groups()
    except Exception as e:
        logger.warning("لیست گروه‌ها خطا داد: %s", e)
        return 0

    if not groups:
        logger.info("هیچ گروهی ثبت نشده — پست ارسال نشد.")
        return 0

    logger.info("ارسال به %d گروه...", len(groups))

    result = await generate_nutrition_post()
    if result is None:
        logger.info("محتوایی تولید نشد.")
        return 0

    content, image_keyword = result
    image_url = search_food_image(image_keyword)

    sent = 0
    failed = 0
    for g in groups:
        try:
            if image_url:
                await bot.send_photo(
                    chat_id=g.chat_id,
                    photo=image_url,
                    caption=with_signature(content),
                )
            else:
                await bot.send_message(
                    chat_id=g.chat_id,
                    text=with_signature(content),
                )
            sent += 1
            logger.info("✅ ارسال موفق به %s (%s)", g.title, g.chat_id)
        except Exception as e:
            failed += 1
            logger.warning("❌ ارسال به %s خطا داد: %s", g.chat_id, e)

    logger.info("پست خودکار: %d موفق، %d ناموفق از %d گروه", sent, failed, len(groups))
    return sent


async def post_auto_content(bot, chat_id: int) -> bool:
    """ارسال به یه گروه خاص (برای تست)."""
    result = await generate_nutrition_post()
    if result is None:
        return False

    content, image_keyword = result
    image_url = search_food_image(image_keyword)

    if image_url:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=with_signature(content),
            )
            return True
        except Exception as e:
            logger.warning("ارسال عکس خطا داد: %s", e)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=with_signature(content),
        )
        return True
    except Exception as e:
        logger.warning("ارسال متن خطا داد: %s", e)
        return False
