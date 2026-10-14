"""AI-powered quiz question generator."""

import json
import logging
import random
import re
from typing import Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


CATEGORIES = [
    "ویتامین‌ها و مواد معدنی",
    "پروتئین و عضله‌سازی",
    "کربوهیدرات و انرژی",
    "چربی‌های سالم",
    "فیبر و سلامت گوارش",
    "آب و هیدراتاسیون",
    "غذاهای ایرانی",
    "کاهش وزن اصولی",
    "تغذیه ورزشی",
    "باورهای اشتباه تغذیه",
    "ایمنی مواد غذایی",
    "خواندن برچسب مواد غذایی",
    "خواب و اشتها",
    "تغذیه گیاهی",
    "ریز‌مغذی‌ها",
]


PROMPT_TEMPLATE = """یک سوال چهارگزینه‌ای حرفه‌ای درباره تغذیه بساز.

📌 دسته: {category}

✅ قوانین:
1. سوال باید علمی، دقیق و مبتنی بر دانش معتبر تغذیه باشه.
2. فارسی روان و طبیعی بنویس.
3. دقیقاً ۴ گزینه بده.
4. فقط یکی از گزینه‌ها درست باشه.
5. یه توضیح کوتاه (۱-۲ جمله) برای جواب درست بنویس.
6. سوال نباید کلیشه‌ای یا تکراری باشه.
7. پاسخ باید قطعی و علمی باشه.

⚠️ خروجی رو دقیقاً به شکل JSON بده، بدون هیچ متن اضافه، بدون ```json، فقط JSON خالص:

{{
  "question": "متن سوال",
  "options": ["گزینه ۱", "گزینه ۲", "گزینه ۳", "گزینه ۴"],
  "correct": 0,
  "explanation": "توضیح کوتاه"
}}

عدد correct ایندکس گزینه درست (۰ تا ۳) است.
"""


FALLBACK_QUESTIONS = [
    {
        "question": "کدام ویتامین به جذب آهن کمک می‌کند؟",
        "options": ["ویتامین A", "ویتامین C", "ویتامین D", "ویتامین K"],
        "correct": 1,
        "explanation": "ویتامین C جذب آهن را چند برابر می‌کند.",
        "category": "ویتامین‌ها و مواد معدنی",
    },
    {
        "question": "چند درصد بدن انسان از آب تشکیل شده؟",
        "options": ["۳۰٪", "۵۰٪", "۶۰٪", "۸۰٪"],
        "correct": 2,
        "explanation": "حدود ۶۰٪ وزن بدن آب است.",
        "category": "آب و هیدراتاسیون",
    },
    {
        "question": "در عدس‌پلو، منبع اصلی پروتئین کدام است؟",
        "options": ["برنج", "عدس", "کشمش", "زعفران"],
        "correct": 1,
        "explanation": "عدس سرشار از پروتئین گیاهی و فیبر است.",
        "category": "غذاهای ایرانی",
    },
    {
        "question": "فیبر روزانه چند گرم توصیه می‌شود؟",
        "options": ["۵-۱۰", "۱۵-۲۰", "۲۵-۳۵", "۵۰+"],
        "correct": 2,
        "explanation": "۲۵-۳۵ گرم فیبر روزانه توصیه می‌شود.",
        "category": "فیبر و سلامت گوارش",
    },
    {
        "question": "کدام برای انرژی سریع قبل از ورزش مناسب است؟",
        "options": ["چربی", "پروتئین", "کربوهیدرات", "فیبر"],
        "correct": 2,
        "explanation": "کربوهیدرات‌ها انرژی سریع فراهم می‌کنند.",
        "category": "تغذیه ورزشی",
    },
    {
        "question": "کدام ماده معدنی برای سلامت استخوان ضروری‌ست؟",
        "options": ["آهن", "روی", "کلسیم", "منیزیم"],
        "correct": 2,
        "explanation": "کلسیم ماده اصلی ساختار استخوان‌ها و دندان‌هاست.",
        "category": "ویتامین‌ها و مواد معدنی",
    },
    {
        "question": "کدام غذا منبع خوب پروتئین گیاهی‌ست؟",
        "options": ["عدس", "برنج", "سیب", "خیار"],
        "correct": 0,
        "explanation": "عدس سرشار از پروتئین گیاهی و فیبر است.",
        "category": "پروتئین و عضله‌سازی",
    },
    {
        "question": "هر گرم چربی چند کالری دارد؟",
        "options": ["۴", "۷", "۹", "۱۲"],
        "correct": 2,
        "explanation": "هر گرم چربی ۹ کالری دارد (بیشترین در بین درشت‌مغذی‌ها).",
        "category": "چربی‌های سالم",
    },
    {
        "question": "کدام نوشیدنی برای هیدراتاسیون بهترینه؟",
        "options": ["نوشابه", "آب", "آبمیوه صنعتی", "چای شیرین"],
        "correct": 1,
        "explanation": "آب بهترین نوشیدنی برای هیدراتاسیون بدنه.",
        "category": "آب و هیدراتاسیون",
    },
    {
        "question": "آیا خوردن شب باعث چاقی می‌شه؟",
        "options": ["بله همیشه", "خیر، کل کالری مهمه", "فقط برای بعضیا", "بستگی به غذا"],
        "correct": 1,
        "explanation": "مهم‌ترین عامل، کل کالری دریافتی در طول روزه، نه ساعت غذا خوردن.",
        "category": "باورهای اشتباه تغذیه",
    },
    {
        "question": "کدام برای صبحانه‌ی پروتئینی مناسبه؟",
        "options": ["نان و مربا", "تخم‌مرغ", "چای و خرما", "کیک"],
        "correct": 1,
        "explanation": "تخم‌مرغ یه منبع عالی پروتئین برای صبحانه‌ست.",
        "category": "پروتئین و عضله‌سازی",
    },
    {
        "question": "کدام میوه ویتامین C بیشتری داره؟",
        "options": ["موز", "پرتقال", "سیب", "انگور"],
        "correct": 1,
        "explanation": "پرتقال یه منبع شناخته‌شده ویتامین C است.",
        "category": "ویتامین‌ها و مواد معدنی",
    },
    {
        "question": "برای کاهش وزن، بهترین کار چیه؟",
        "options": ["حذف صبحانه", "رژیم سخت", "کالری منفی روزانه", "خواب کافی و ورزش"],
        "correct": 3,
        "explanation": "خواب کافی و ورزش منظم بهترین راه طولانی‌مدته.",
        "category": "کاهش وزن اصولی",
    },
    {
        "question": "آب قبل از غذا چه تأثیری داره؟",
        "options": ["افزایش اشتها", "کاهش اشتها", "بی‌تأثیر", "افزایش وزن"],
        "correct": 1,
        "explanation": "آب قبل غذا احساس سیری ایجاد می‌کنه و اشتها رو کم می‌کنه.",
        "category": "کاهش وزن اصولی",
    },
    {
        "question": "کدام ویتامین با نور خورشید در پوست ساخته می‌شه؟",
        "options": ["A", "C", "D", "K"],
        "correct": 2,
        "explanation": "ویتامین D با نور خورشید در پوست ساخته می‌شه.",
        "category": "ویتامین‌ها و مواد معدنی",
    },
]


def _extract_json(text: str) -> Optional[dict]:
    """Extract JSON from AI response (handles code blocks, extra text)."""
    if not text:
        return None

    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


def _validate_question(data: dict) -> bool:
    """Check if the parsed JSON has the correct structure."""
    if not isinstance(data, dict):
        return False
    if "question" not in data or "options" not in data:
        return False
    if not isinstance(data["options"], list) or len(data["options"]) != 4:
        return False
    if "correct" not in data:
        return False
    try:
        c = int(data["correct"])
    except (ValueError, TypeError):
        return False
    if c < 0 or c > 3:
        return False
    if not data.get("question"):
        return False
    if not all(isinstance(o, str) and o.strip() for o in data["options"]):
        return False
    return True


def _fallback_question() -> dict:
    """Return a copy of a random fallback question."""
    q = random.choice(FALLBACK_QUESTIONS).copy()
    q["options"] = list(q["options"])
    return q


async def generate_question(category: Optional[str] = None) -> dict:
    """Generate a quiz question using AI. Falls back to predefined on error."""
    settings = get_settings()

    # اگه کلید API نیست، fallback
    if not settings.deepseek_api_key:
        logger.info("کلید API تنظیم نشده — استفاده از سوالات آماده.")
        return _fallback_question()

    cat = category or random.choice(CATEGORIES)
    prompt = PROMPT_TEMPLATE.format(category=cat)

    try:
        # import داخل تابع تا circular import پیش نیاد
        from groq import AsyncGroq

        model_name = settings.deepseek_model or "llama-3.1-8b-instant"
        logger.info("کوییز با مدل: %s", model_name)

        client = AsyncGroq(api_key=settings.deepseek_api_key)

        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "تو یک متخصص تغذیه هستی که سوالات چهارگزینه‌ای فارسی می‌سازد. "
                        "فقط JSON خالص برگردان، هیچ متن اضافی نده."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=600,
        )

        text = response.choices[0].message.content
        if not text:
            raise ValueError("AI returned empty")

        data = _extract_json(text)
        if data is None or not _validate_question(data):
            logger.warning("Invalid AI quiz JSON: %s", text[:200])
            raise ValueError("Invalid JSON structure")

        return {
            "question": str(data["question"]).strip()[:500],
            "options": [str(o).strip()[:100] for o in data["options"]],
            "correct": int(data["correct"]),
            "explanation": str(data.get("explanation", "")).strip()[:400],
            "category": cat,
        }

    except Exception as e:
        logger.warning("AI question generation failed: %s — using fallback", e)
        return _fallback_question()
