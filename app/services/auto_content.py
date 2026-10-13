"""تولید و ارسال خودکار محتوای تغذیه‌ای با عکس به گروه‌ها."""

import logging
import random

import httpx
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
#  دسته‌بندی‌های عکس (از Foodish و TheMealDB)
# ============================================================

FOODISH_CATEGORIES = [
    "biryani", "burger", "butter-chicken", "dessert",
    "dosa", "idly", "pasta", "pizza", "rice", "samosa",
]

# TheMealDB دسته‌های عکس: Beef, Breakfast, Chicken, Dessert, Goat,
# Lamb, Miscellaneous, Pasta, Pork, Seafood, Side, Starter,
# Vegan, Vegetarian
THEMEALDB_CATEGORIES = [
    "Breakfast", "Chicken", "Dessert", "Pasta",
    "Seafood", "Vegan", "Vegetarian", "Miscellaneous",
]


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
#  جستجوی عکس — چند منبع با Fallback
# ============================================================

async def _get_foodish_image() -> str | None:
    """عکس رندوم از Foodish API (بدون کلید)."""
    cat = random.choice(FOODISH_CATEGORIES)
    url = f"https://foodish-api.com/api/images/{cat}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code == 200:
                # Foodish گاهی redirect می‌کنه، گاهی JSON می‌ده
                ct = r.headers.get("content-type", "")
                if "application/json" in ct:
                    data = r.json()
                    img = data.get("image")
                    if img and img.startswith("http"):
                        return img
                elif "image" in ct:
                    # خود پاسخ یه عکسه — از URL نهایی استفاده کن
                    return str(r.url)
    except Exception as e:
        logger.debug("Foodish خطا: %s", e)
    return None


async def _get_themealdb_image() -> str | None:
    """عکس رندوم از TheMealDB (بدون کلید)."""
    cat = random.choice(THEMEALDB_CATEGORIES)
    url = f"https://www.themealdb.com/api/json/v1/1/filter.php?c={cat}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                meals = data.get("meals") or []
                if meals:
                    m = random.choice(meals)
                    img = m.get("strMealThumb")
                    if img and img.startswith("http"):
                        return img
    except Exception as e:
        logger.debug("TheMealDB خطا: %s", e)
    return None


async def _get_duckduckgo_image(keyword: str) -> str | None:
    """عکس از DuckDuckGo (تلاش نهایی)."""
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
        logger.debug("DuckDuckGo خطا: %s", e)
    return None


async def search_food_image(keyword: str) -> str | None:
    """جستجوی عکس با چندین منبع (به ترتیب)."""
    # ۱) Foodish
    img = await _get_foodish_image()
    if img:
        logger.info("عکس از Foodish گرفته شد.")
        return img

    # ۲) TheMealDB
    img = await _get_themealdb_image()
    if img:
        logger.info("عکس از TheMealDB گرفته شد.")
        return img

    # ۳) DuckDuckGo
    img = await _get_duckduckgo_image(keyword)
    if img:
        logger.info("عکس از DuckDuckGo گرفته شد.")
        return img

    logger.warning("هیچ عکسی پیدا نشد.")
    return None


# ============================================================
#  ارسال با عکس + کپشن
# ============================================================

async def _send_with_photo(bot, chat_id: int, content: str, keyword: str) -> bool:
    """ارسال محتوا با عکس. اگه عکس نشد، فقط متن."""
    image_url = await search_food_image(keyword)

    if image_url:
        try:
            await bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=with_signature(content),
            )
            logger.info("✅ عکس + متن ارسال شد به %s", chat_id)
            return True
        except Exception as e:
            logger.warning("ارسال عکس خطا داد: %s", e)
            # تلاش دوم با عکس دیگه
            try:
                image_url2 = await _get_foodish_image() or await _get_themealdb_image()
                if image_url2:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=image_url2,
                        caption=with_signature(content),
                    )
                    logger.info("✅ عکس (تلاش دوم) + متن ارسال شد.")
                    return True
            except Exception as e2:
                logger.warning("تلاش دوم عکس خطا داد: %s", e2)

    # Fallback: فقط متن
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=with_signature(content),
        )
        logger.info("✅ فقط متن ارسال شد (بدون عکس).")
        return True
    except Exception as e:
        logger.warning("ارسال متن هم خطا داد: %s", e)
        return False


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

    sent = 0
    for g in groups:
        try:
            ok = await _send_with_photo(bot, g.chat_id, content, image_keyword)
            if ok:
                sent += 1
        except Exception as e:
            logger.warning("❌ ارسال به %s خطا داد: %s", g.chat_id, e)

    logger.info("پست خودکار: %d از %d گروه موفق.", sent, len(groups))
    return sent


async def post_auto_content(bot, chat_id: int) -> bool:
    """ارسال به یه گروه خاص (برای تست)."""
    result = await generate_nutrition_post()
    if result is None:
        return False

    content, image_keyword = result
    return await _send_with_photo(bot, chat_id, content, image_keyword)
