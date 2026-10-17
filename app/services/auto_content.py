"""تولید و ارسال خودکار محتوای تغذیه‌ای با عکس هوشمند و مرتبط."""

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


PREFERRED_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "gemma2-9b-it",
    "mixtral-8x7b-32768",
]


# 🧠 پرامپت ارتقایافته: جلوگیری از منابع جعلی و تضمین دقت علمی
SYSTEM_PROMPT = """تو یک متخصص تغذیه و سلامت هستی که برای یک گروه تلگرام فارسی محتوا تولید می‌کنی.

وظیفه تو:
1. یک متن کوتاه، جذاب و کاملاً علمی به فارسی بنویس.
2. متن شامل یک عنوان جذاب و توضیح ۳ تا ۴ خطی باشد.
3. 🚨 هر ادعا باید پشتوانه علمی واقعی داشته باشد (WHO، NIH، Mayo Clinic، Harvard Health، NHS).
4. 🚨 هرگز منبع جعلی یا نام مقاله‌ای که وجود ندارد نساز. فقط از منابع معتبر و شناخته‌شده بالا استفاده کن.
5. از اغراق، وعده‌های قطعی، و ادعاهای درمانی خودداری کن. اگر عددی را دقیق نمی‌دانی، از کلمه «تقریبی» استفاده کن.
6. در انتها فقط نام منبع معتبر را ذکر کن.
7. هرگز از عبارات انگلیسی در متن اصلی استفاده نکن.

خروجی باید دقیقاً به این فرمت باشد (هیچ چیز اضافه ننویس):

IMAGE_KEYWORD: [یک عبارت انگلیسی ۴-۶ کلمه‌ای بسیار دقیق و توصیفی که دقیقاً همان موضوع متن را توصیف کند. این عبارت باید شامل: نوع غذا/ماده، ویژگی ظاهری، و زمینه‌ی موضوعی باشد. مثال: grilled salmon fillet lemon herbs heart health]

TITLE: [عنوان جذاب فارسی]

BODY: [متن ۳ تا ۴ خطی فارسی]

SOURCE: [نام منبع معتبر مثل WHO یا Harvard Health]
"""


async def _get_available_models(api_key: str) -> list[str]:
    try:
        client = AsyncGroq(api_key=api_key)
        response = await client.models.list()
        return [m.id for m in response.data]
    except Exception as e:
        logger.warning("خطا در دریافت لیست مدل‌ها: %s", e)
        return []


async def _pick_model(api_key: str, requested: str = "") -> str | None:
    available = await _get_available_models(api_key)

    if available:
        logger.info("مدل‌های موجود Groq: %s", ", ".join(available[:10]))

    if requested and requested in available:
        return requested

    for m in PREFERRED_MODELS:
        if m in available:
            return m

    if available:
        return available[0]

    return requested or "llama-3.3-70b-versatile"


async def generate_nutrition_post() -> tuple[str, str] | None:
    settings = get_settings()
    
    # پشتیبانی همزمان از کلیدهای Groq و DeepSeek
    api_key = getattr(settings, 'groq_api_key', '') or getattr(settings, 'deepseek_api_key', '')
    req_model = getattr(settings, 'groq_model', '') or getattr(settings, 'deepseek_model', '')

    if not api_key:
        logger.warning("کلید API تنظیم نشده.")
        return None

    # لیست مدل‌هایی که در صورت خطا یا پاسخ خالی امتحان می‌شوند
    # مدل qwen در لیست لاگ شما بود و بسیار قوی است
    models_to_try = [req_model, "qwen/qwen3.8-27b", "openai/gpt-oss-120b"] if req_model else ["qwen/qwen3.8-27b", "openai/gpt-oss-120b"]
    
    topic = random.choice(SEARCH_TOPICS)
    client = AsyncGroq(api_key=api_key)

    for model_name in models_to_try:
        if not model_name: 
            continue
        
        try:
            logger.info("تلاش برای تولید محتوا با مدل: %s", model_name)

            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"موضوع: {topic}"},
                ],
                temperature=0.3,
                max_tokens=2500,  # 🔥 افزایش یافت تا مدل‌های استدلالی فرصت جواب دادن داشته باشند
            )

            raw = response.choices[0].message.content
            
            # اگر پاسخ خالی بود، سراغ مدل بعدی برو
            if not raw or not raw.strip():
                logger.warning("پاسخ خالی از مدل %s دریافت شد. تلاش با مدل بعدی...", model_name)
                continue

            parsed = _parse_ai_output(raw)
            if parsed is None:
                logger.warning("فرمت خروجی AI برای مدل %s قابل پارس نبود.", model_name)
                # اگر پارس نشد، خود متن خام را بفرست
                return raw.strip(), "healthy nutrition food"

            title, body, source, keyword = parsed
            final_text = f"📌 {title}\n\n{body}\n\n🔗 منبع: {source}"
            logger.info("✅ محتوا با موفقیت با مدل %s تولید شد. کلمه کلیدی عکس: %s", model_name, keyword)
            return final_text, keyword

        except Exception as e:
            logger.warning("خطا در تولید با مدل %s: %s", model_name, e)
            continue # سراغ مدل بعدی برو

    logger.error("همه مدل‌ها خطا دادند یا پاسخ خالی برگرداندند.")
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


async def _get_unsplash_image(keyword: str, api_key: str) -> str | None:
    """عکس باکیفیت از Unsplash."""
    url = "https://api.unsplash.com/search/photos"
    params = {
        "query": keyword,
        "per_page": 10,
        "orientation": "landscape",
        "client_id": api_key,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params=params)
            if r.status_code == 200:
                data = r.json()
                results = data.get("results") or []
                random.shuffle(results)
                for item in results:
                    img = item.get("urls", {}).get("regular")
                    if img:
                        return img
    except Exception as e:
        logger.debug("Unsplash خطا: %s", e)
    return None


async def _get_duckduckgo_image(keyword: str) -> str | None:
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(keyword, max_results=15))
            if results:
                random.shuffle(results)
                for item in results:
                    url = item.get("image")
                    if url and url.startswith("http"):
                        return url
    except Exception as e:
        logger.debug("DuckDuckGo خطا: %s", e)
    return None


async def _get_themealdb_image(keyword: str) -> str | None:
    kw_lower = keyword.lower()
    cat = None
    if any(w in kw_lower for w in ["chicken", "protein", "meat", "beef", "lamb"]):
        cat = "Chicken"
    elif any(w in kw_lower for w in ["fish", "salmon", "seafood", "tuna", "shrimp"]):
        cat = "Seafood"
    elif any(w in kw_lower for w in ["vegetable", "salad", "vegan", "green", "spinach"]):
        cat = "Vegetarian"
    elif any(w in kw_lower for w in ["fruit", "berry", "apple", "orange", "banana"]):
        cat = "Dessert"
    elif any(w in kw_lower for w in ["pasta", "rice", "grain", "bread", "cereal"]):
        cat = "Pasta"
    elif any(w in kw_lower for w in ["breakfast", "morning", "egg", "oats"]):
        cat = "Breakfast"
    else:
        return None

    url = f"https://www.themealdb.com/api/json/v1/1/filter.php?c={cat}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            if r.status_code == 200:
                data = r.json()
                meals = data.get("meals") or []
                if meals:
                    random.shuffle(meals)
                    for m in meals[:5]:
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
    """جستجوی عکس — اولویت با تطابق و عدم تکرار."""
    settings = get_settings()

    # ۱. Unsplash
    if settings.unsplash_access_key:
        for attempt in range(2):
            img = await _get_unsplash_image(keyword, settings.unsplash_access_key)
            if img and not await repo.image_already_sent(img):
                logger.info("✅ عکس از Unsplash: %s", keyword)
                return img

    # ۲. DuckDuckGo
    for attempt in range(2):
        img = await _get_duckduckgo_image(keyword)
        if img and not await repo.image_already_sent(img):
            logger.info("✅ عکس از DuckDuckGo: %s", keyword)
            return img

    # ۳. TheMealDB
    img = await _get_themealdb_image(keyword)
    if img and not await repo.image_already_sent(img):
        logger.info("✅ عکس از TheMealDB: %s", keyword)
        return img

    # ۴. Foodish (آخرین راه‌حل)
    for _ in range(3):
        img = await _get_foodish_image()
        if img and not await repo.image_already_sent(img):
            logger.info("✅ عکس از Foodish (رندوم)")
            return img

    logger.warning("هیچ عکس جدیدی پیدا نشد.")
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
            await repo.mark_image_sent(image_url, keyword)
            logger.info("✅ عکس + متن ارسال شد به %s", chat_id)
            return True
        except Exception as e:
            logger.warning("ارسال عکس خطا داد: %s", e)
            try:
                backup = await _get_foodish_image()
                if backup and not await repo.image_already_sent(backup):
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=backup,
                        caption=with_signature(content),
                    )
                    await repo.mark_image_sent(backup, keyword)
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
