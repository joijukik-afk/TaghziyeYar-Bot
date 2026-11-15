"""تولید و ارسال خودکار محتوای تغذیه‌ای با عکس هوشمند و مرتبط (ضد تکرار)"""

import io
import logging
import random
import re
import urllib.parse
from collections import deque

import httpx
import telegram
from groq import AsyncGroq
from PIL import Image

from app.config import get_settings
from app.database import repository as repo
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

# 👈 محدودیت کپشن تلگرام
TELEGRAM_CAPTION_MAX = 1024

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

MODELS_TO_TRY = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
]

# 🧠 حافظه ضد تکرار برای موضوعات
_recent_topics = deque(maxlen=15)


def _get_unique_topic() -> str:
    available = [t for t in SEARCH_TOPICS if t not in _recent_topics]
    if not available:
        _recent_topics.clear()
        available = SEARCH_TOPICS

    chosen = random.choice(available)
    _recent_topics.append(chosen)
    return chosen


SYSTEM_PROMPT = """تو یک متخصص تغذیه و سلامت هستی که برای یک گروه تلگرام فارسی محتوا تولید می‌کنی.

وظیفه تو:
1. یک متن کوتاه، جذاب و کاملاً علمی به فارسی بنویس.
2. متن شامل یک عنوان جذاب و توضیح ۳ تا ۴ خطی باشد.
3. 🚨 هر ادعا باید پشتوانه علمی واقعی داشته باشد (WHO، NIH، Mayo Clinic، Harvard Health، NHS).
4. 🚨 هرگز منبع جعلی یا نام مقاله‌ای که وجود ندارد نساز.
5. از اغراق، وعده‌های قطعی، و ادعاهای درمانی خودداری کن.
6. در انتها فقط نام منبع معتبر را ذکر کن.
7. هرگز از عبارات انگلیسی در متن اصلی استفاده نکن.
8. 🚨 بسیار مهم: در این درخواست، زاویه دید جدیدی اتخاذ کن و از کلیشه‌های تکراری پرهیز کن.

خروجی باید دقیقاً به این فرمت باشد (هیچ چیز اضافه ننویس):

IMAGE_KEYWORD: [یک عبارت انگلیسی ۴-۶ کلمه‌ای بسیار دقیق و توصیفی]

TITLE: [عنوان جذاب فارسی]

BODY: [متن ۳ تا ۴ خطی فارسی]

SOURCE: [نام منبع معتبر مثل WHO یا Harvard Health]
"""


async def generate_nutrition_post() -> tuple[str, str] | None:
    settings = get_settings()
    api_key = getattr(settings, 'groq_api_key', '') or getattr(settings, 'deepseek_api_key', '')
    req_model = getattr(settings, 'groq_model', '') or getattr(settings, 'deepseek_model', '')

    if not api_key:
        logger.warning("کلید API تنظیم نشده.")
        return None

    models_to_try = [req_model] + MODELS_TO_TRY if req_model else MODELS_TO_TRY

    topic = _get_unique_topic()
    logger.info("📝 موضوع جدید انتخاب شده: %s", topic)

    client = AsyncGroq(api_key=api_key)

    for model_name in models_to_try:
        if not model_name:
            continue
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"موضوع: {topic}"},
                ],
                temperature=0.4,
                max_tokens=2500,
            )

            raw = response.choices[0].message.content
            if not raw or not raw.strip():
                continue

            parsed = _parse_ai_output(raw)
            if parsed is None:
                return raw.strip(), f"healthy food {random.randint(1, 1000)}"

            title, body, source, keyword = parsed
            final_text = f"📌 {title}\n\n{body}\n\n🔗 منبع: {source}"
            return final_text, keyword

        except Exception as e:
            logger.warning("خطا در تولید با مدل %s: %s", model_name, e)
            continue

    return None


def _parse_ai_output(raw: str) -> tuple[str, str, str, str] | None:
    try:
        text = raw.replace("**", "").strip()
        kw_match = re.search(r"IMAGE_KEYWORD\s*:\s*(.+?)(?=\n\s*TITLE|\n\s*BODY|\n\s*SOURCE|\Z)", text, re.DOTALL | re.IGNORECASE)
        keyword = kw_match.group(1).strip() if kw_match else "healthy nutrition food"
        keyword = keyword.split("\n")[0].strip()
        title_match = re.search(r"TITLE\s*:\s*(.+?)(?=\n\s*BODY|\n\s*SOURCE|\Z)", text, re.DOTALL | re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else ""
        title = title.split("\n")[0].strip()
        body_match = re.search(r"BODY\s*:\s*(.+?)(?=\n\s*SOURCE|\Z)", text, re.DOTALL | re.IGNORECASE)
        body = body_match.group(1).strip() if body_match else ""
        source_match = re.search(r"SOURCE\s*:\s*(.+?)\Z", text, re.DOTALL | re.IGNORECASE)
        source = source_match.group(1).strip() if source_match else ""
        source = source.split("\n")[0].strip()
        if not title or not body:
            return None
        return title, body, source, keyword
    except Exception as e:
        logger.warning("خطا در پارس: %s", e)
        return None


# 👈 استفاده از یک Client مشترک برای همه درخواست‌های HTTP
_http_client = httpx.AsyncClient(timeout=15.0)


async def _get_unsplash_image(keyword: str, api_key: str) -> str | None:
    url = "https://api.unsplash.com/search/photos"
    params = {"query": keyword, "per_page": 10, "orientation": "landscape", "client_id": api_key}
    try:
        r = await _http_client.get(url, params=params)
        if r.status_code == 200:
            results = r.json().get("results") or []
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
        import asyncio

        def _sync_search():
            with DDGS() as ddgs:
                return list(ddgs.images(keyword, max_results=15))

        results = await asyncio.to_thread(_sync_search)
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
    if any(w in kw_lower for w in ["chicken", "protein", "meat", "beef", "lamb"]): cat = "Chicken"
    elif any(w in kw_lower for w in ["fish", "salmon", "seafood", "tuna", "shrimp"]): cat = "Seafood"
    elif any(w in kw_lower for w in ["vegetable", "salad", "vegan", "green", "spinach"]): cat = "Vegetarian"
    elif any(w in kw_lower for w in ["fruit", "berry", "apple", "orange", "banana"]): cat = "Dessert"
    elif any(w in kw_lower for w in ["pasta", "rice", "grain", "bread", "cereal"]): cat = "Pasta"
    elif any(w in kw_lower for w in ["breakfast", "morning", "egg", "oats"]): cat = "Breakfast"
    else: return None

    url = f"https://www.themealdb.com/api/json/v1/1/filter.php?c={cat}"
    try:
        r = await _http_client.get(url)
        if r.status_code == 200:
            meals = r.json().get("meals") or []
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
    cat = random.choice(["biryani", "burger", "butter-chicken", "dessert", "dosa", "pasta", "pizza", "rice", "samosa"])
    url = f"https://foodish-api.com/api/images/{cat}"
    try:
        r = await _http_client.get(url, follow_redirects=True)
        if r.status_code == 200:
            if "application/json" in r.headers.get("content-type", ""): return r.json().get("image")
            elif "image" in r.headers.get("content-type", ""): return str(r.url)
    except Exception as e:
        logger.debug("Foodish خطا: %s", e)
    return None


async def _get_pollinations_image(keyword: str) -> str | None:
    seed = random.randint(1, 999999)
    prompt = f"{keyword}, professional food photography, high detail, random angle, seed {seed}"
    encoded = urllib.parse.quote(prompt)

    settings = get_settings()
    api_key = getattr(settings, 'pollinations_api_key', '')

    if api_key:
        return f"https://gen.pollinations.ai/image/{encoded}?width=1024&height=1024&nologo=true&model=flux&key={api_key}&seed={seed}"
    else:
        return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&seed={seed}"


async def search_food_image(keyword: str) -> str | None:
    settings = get_settings()

    if settings.unsplash_access_key:
        for attempt in range(2):
            img = await _get_unsplash_image(keyword, settings.unsplash_access_key)
            if img and not await repo.image_already_sent(img): return img

    for attempt in range(2):
        img = await _get_duckduckgo_image(keyword)
        if img and not await repo.image_already_sent(img): return img

    img = await _get_themealdb_image(keyword)
    if img and not await repo.image_already_sent(img): return img

    for _ in range(3):
        img = await _get_foodish_image()
        if img and not await repo.image_already_sent(img): return img

    logger.warning("استفاده از هوش مصنوعی برای ساخت عکس پست...")
    ai_img = await _get_pollinations_image(keyword)
    return ai_img


async def _download_and_validate_image(image_url: str) -> io.BytesIO | None:
    """دانلود و اعتبارسنجی عکس (خروجی: BytesIO آماده ارسال)"""
    try:
        resp = await _http_client.get(image_url, timeout=45.0)
        resp.raise_for_status()

        # 👈 اعتبارسنجی واقعی عکس با Pillow
        img_io = io.BytesIO(resp.content)
        Image.open(img_io).verify()
        img_io.seek(0)
        img_io.name = 'post_image.jpg'
        return img_io
    except Exception as e:
        logger.warning(f"Image download/validation failed: {e}")
        return None


def _truncate_caption(content: str) -> str:
    """کوتاه کردن کپشن در صورت عبور از حد مجاز تلگرام"""
    text = with_signature(content)
    if len(text) <= TELEGRAM_CAPTION_MAX:
        return text
    signature = get_settings().signature
    body_max = TELEGRAM_CAPTION_MAX - len(signature) - 3
    return text[:body_max].rstrip() + "…" + signature


async def _send_prepared_content(bot, chat_id: int, content: str, image_io: io.BytesIO | None, image_url: str | None, keyword: str) -> bool:
    """ارسال محتوای آماده شده (بدون جستجوی مجدد عکس)"""
    try:
        if image_io:
            fresh_io = io.BytesIO(image_io.getvalue())
            fresh_io.name = 'post_image.jpg'
            await bot.send_photo(
                chat_id=chat_id, photo=fresh_io, caption=_truncate_caption(content)
            )
            return True
    except telegram.error.Forbidden as e:
        raise e
    except Exception as e:
        logger.warning(f"ارسال عکس به {chat_id} خطا داد: {e}")

    try:
        await bot.send_message(chat_id=chat_id, text=with_signature(content))
        return True
    except telegram.error.Forbidden as e:
        raise e
    except Exception as e:
        return False


async def broadcast_auto_content(bot) -> int:
    try:
        groups = await repo.list_all_groups()
    except Exception:
        return 0
    if not groups: return 0

    result = await generate_nutrition_post()
    if result is None: return 0

    content, image_keyword = result

    # 👈 ۱. عکس فقط یک‌بار جستجو و دانلود می‌شود
    image_url = await search_food_image(image_keyword)
    image_io = await _download_and_validate_image(image_url) if image_url else None

    if image_url and image_io:
        await repo.mark_image_sent(image_url, image_keyword)

    sent = 0
    # 👈 ۲. حالا همان عکس آماده به همه گروه‌ها ارسال می‌شود
    for g in groups:
        try:
            ok = await _send_prepared_content(bot, g.chat_id, content, image_io, image_url, image_keyword)
            if ok: sent += 1
        except telegram.error.Forbidden:
            await repo.deactivate_group(chat_id=g.chat_id)
        except Exception as e:
            logger.debug(f"Broadcast to {g.chat_id} failed: {e}")
    return sent


async def post_auto_content(bot, chat_id: int) -> bool:
    result = await generate_nutrition_post()
    if result is None: return False

    content, image_keyword = result
    image_url = await search_food_image(image_keyword)
    image_io = await _download_and_validate_image(image_url) if image_url else None

    if image_url and image_io:
        await repo.mark_image_sent(image_url, image_keyword)

    try:
        return await _send_prepared_content(bot, chat_id, content, image_io, image_url, image_keyword)
    except telegram.error.Forbidden:
        await repo.deactivate_group(chat_id=chat_id)
        return False
