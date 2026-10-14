"""تولید و ارسال خودکار محتوای تغذیه‌ای با عکس مرتبط به گروه‌ها."""

import logging
import random
import re

import httpx
from groq import AsyncGroq

from app.config import get_settings
from app.database import repository as repo
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)


SEARCH_TOPICS = [
    "آخرین یافته‌های علمی 2025 درباره تغذیه و سلامت",
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
    "نقش ریز‌مغذی‌ها در انرژی روزانه",
    "تاثیر روزه‌داری متناوب بر سلامت",
    "میکروبیوم روده و تغذیه",
    "خطرات مصرف نوشیدنی‌های انرژی‌زا",
    "بهترین منابع پروتئین گیاهی",
]


SYSTEM_PROMPT = """تو یک متخصص تغذیه و سلامت هستی که برای یک گروه تلگرام فارسی محتوا تولید می‌کنی.

وظیفه تو:
1. با ابزار جستجوی وب، جدیدترین اطلاعات علمی (سال 2024 و 2025) را پیدا کن.
2. فقط از منابع معتبر استفاده کن (WHO، NIH، Mayo Clinic، Harvard Health، NHS، PubMed).
3. یک متن کوتاه، جذاب و کاربردی به فارسی بنویس.
4. متن شامل یک عنوان جذاب و توضیح ۳ تا ۴ خطی باشد.
5. هر ادعا باید پشتوانه علمی داشته باشد.
6. از اغراق، وعده‌های قطعی، و ادعاهای درمانی خودداری کن.
7. در انتها منبع دقیق (نام + لینک) ذکر کن.
8. هرگز از عبارات انگلیسی در متن اصلی استفاده نکن.

خروجی باید دقیقاً به این فرمت باشد (هیچ چیز اضافه ننویس):

IMAGE_KEYWORD: [یک عبارت انگلیسی ۳-۴ کلمه‌ای که بهترین عکس را برای این موضوع توصیف می‌کند]

TITLE: [عنوان جذاب فارسی]

BODY: [متن ۳ تا ۴ خطی فارسی]

SOURCE: [نام منبع + لینک]
"""


async def generate_nutrition_post() -> tuple[str, str] | None:
    """تولید پست جدید. Returns (text, image_keyword) یا None."""
    settings = get_settings()

    if not settings.deepseek_api_key:
        logger.warning("کلید API تنظیم نشده.")
        return None

    topic = random.choice(SEARCH_TOPICS)

    try:
        client = AsyncGroq(api_key=settings.deepseek_api_key)

        # ⚡ اینجا از متغیر محیطی استفاده می‌کنه، نه هارد‌کد!
        model_name = settings.deepseek_model or "llama-3.1-8b-instant"
        logger.info("استفاده از مدل: %s", model_name)

        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"موضوع: {topic}"},
            ],
            tools=[{"type": "browser_search"}],
            tool_choice="auto",
            temperature=0.6,
            max_tokens=1000,
        )

        raw = response.choices[0].message.content
        if not raw:
            logger.warning("پاسخ خالی از AI.")
            return None

        parsed = _parse_ai_output(raw)
        if parsed is None:
            logger.warning("فرمت خروجی AI قابل پارس نبود.")
            return raw.strip(), "healthy nutrition food"

        title, body, source, keyword = parsed
        final_text = f"📌 {title}\n\n{body}\n\n🔗 منبع: {source}"
        return final_text, keyword

    except Exception as e:
        logger.warning("خطا در تولید: %s", e)
        return None


def _parse_ai_output(raw: str) -> tuple[str, str, str, str] | None:
    try:
        text = raw.replace("**", "").strip()

        kw_match = re.search(
            r"IMAGE_KEYWORD\s*:\s*(.+?)(?=\n\s*TITLE|\n\s*BODY|\n\s*SOURCE|\Z)",
            text, re.DOTALL | re.IGNORECASE
        )
        keyword = kw_match.group(1).strip() if kw_match else "healthy nutrition food"
        keyword = keyword.split("\n")[0].strip()

        title_match = re.search(
            r"TITLE\s*:\s*(.+?)(?=\n\s*BODY|\n\s*SOURCE|\Z)",
            text, re.DOTALL | re.IGNORECASE
        )
        title = title_match.group(1).strip() if title_match else ""
        title = title.split("\n")[0].strip()

        body_match = re.search(
            r"BODY\s*:\s*(.+?)(?=\n\s*SOURCE|\Z)",
            text, re.DOTALL | re.IGNORECASE
        )
        body = body_match.group(1).strip() if body_match else ""

        source_match = re.search(
            r"SOURCE\s*:\s*(.+?)\Z",
            text, re.DOTALL | re.IGNORECASE
        )
        source = source_match.group(1).strip() if source_match else ""
        source = source.split("\n")[0].strip()

        if not title or not body:
            return None

        return title, body, source, keyword

    except Exception as e:
        logger.warning("خطا در پارس: %s", e)
        return None


async def _get_duckduckgo_image(keyword: str) -> str | None:
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(keyword, max_results=8))
            if results:
                top = results[:3]
                chosen = random.choice(top)
                url = chosen.get("image")
                if url and url.startswith("http"):
                    return url
    except Exception as e:
        logger.debug("DuckDuckGo خطا: %s", e)
    return None


async def _get_themealdb_image(keyword: str) -> str | None:
    kw_lower = keyword.lower()
    cat = None
    if any(w in kw_lower for w in ["chicken", "protein", "meat"]):
        cat = "Chicken"
    elif any(w in kw_lower for w in ["fish", "salmon", "seafood", "tuna"]):
        cat = "Seafood"
    elif any(w in kw_lower for w in ["vegetable", "salad", "vegan", "green"]):
        cat = "Vegetarian"
    elif any(w in kw_lower for w in ["fruit", "berry", "apple", "orange"]):
        cat = "Dessert"
    elif any(w in kw_lower for w in ["pasta", "rice", "grain", "bread"]):
        cat = "Pasta"
    elif any(w in kw_lower for w in ["breakfast", "morning", "egg"]):
        cat = "Breakfast"
    else:
        cat = random.choice([
            "Breakfast", "Chicken", "Seafood",
            "Vegetarian", "Vegan", "Miscellaneous",
        ])

    url = f"https://www.themealdb.com/api/json/v1/1/filter.php?c={cat}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                meals = data.get("meals") or []
                if meals:
                    m = random.choice(meals[:5])
                    img = m.get("strMealThumb")
                    if img and img.startswith("http"):
                        return img
    except Exception as e:
        logger.debug("TheMealDB خطا: %s", e)
    return None


async def _get_foodish_image() -> str | None:
    cat = random.choice([
        "biryani", "burger", "butter-chicken", "dessert",
        "dosa", "pasta", "pizza", "rice", "samosa",
    ])
    url = f"https://foodish-api.com/api/images/{cat}"
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code == 200:
                ct = r.headers.get("content-type", "")
                if "application/json" in ct:
                    data = r.json()
                    img = data.get("image")
                    if img and img.startswith("http"):
                        return img
                elif "image" in ct:
                    return str(r.url)
    except Exception as e:
        logger.debug("Foodish خطا: %s", e)
    return None


async def search_food_image(keyword: str) -> str | None:
    img = await _get_duckduckgo_image(keyword)
    if img:
        logger.info("✅ عکس از DuckDuckGo برای: %s", keyword)
        return img

    img = await _get_themealdb_image(keyword)
    if img:
        logger.info("✅ عکس از TheMealDB برای: %s", keyword)
        return img

    img = await _get_foodish_image()
    if img:
        logger.info("✅ عکس از Foodish (رندوم)")
        return img

    logger.warning("هیچ عکسی پیدا نشد.")
    return None


async def _send_with_photo(bot, chat_id: int, content: str, keyword: str) -> bool:
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

            try:
                backup = await _get_themealdb_image(keyword) or await _get_foodish_image()
                if backup:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=backup,
                        caption=with_signature(content),
                    )
                    logger.info("✅ عکس (تلاش دوم) ارسال شد.")
                    return True
            except Exception as e2:
                logger.warning("تلاش دوم هم خطا: %s", e2)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=with_signature(content),
        )
        logger.info("✅ فقط متن ارسال شد (بدون عکس).")
        return True
    except Exception as e:
        logger.warning("ارسال متن هم خطا: %s", e)
        return False


async def broadcast_auto_content(bot) -> int:
    try:
        groups = await repo.list_all_groups()
    except Exception as e:
        logger.warning("لیست گروه‌ها خطا: %s", e)
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
            logger.warning("❌ ارسال به %s خطا: %s", g.chat_id, e)

    logger.info("پست خودکار: %d از %d گروه موفق.", sent, len(groups))
    return sent


async def post_auto_content(bot, chat_id: int) -> bool:
    result = await generate_nutrition_post()
    if result is None:
        return False

    content, image_keyword = result
    return await _send_with_photo(bot, chat_id, content, image_keyword)
