"""AI-powered quiz question generator with anti-repetition memory."""

import json
import logging
import random
import re
from typing import Optional

import aiosqlite

from app.config import get_settings

logger = logging.getLogger(__name__)

# مسیر دیتابیس برای ذخیره تاریخچه سوالات کوییز
DB_PATH = "quiz_history.db"


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
6. پاسخ باید قطعی و علمی باشه.

🚨 قانون بسیار مهم (عدم تکرار):
سوال تو نباید شبیه به هیچ‌کدام از سوالات زیر باشد (نه از نظر مفهوم و نه از نظر گزینه‌ها). سوال کاملاً جدید بساز:
{history}

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
]


# ==========================================
#  🧠 سیستم حافظه (Memory System)
# ==========================================

async def _init_db() -> None:
    """ساخت جدول تاریخچه در صورت عدم وجود."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS used_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def _get_recent_questions(limit: int = 20) -> list[str]:
    """دریافت ۲۰ سوال آخر برای جلوگیری از تکرار."""
    await _init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT question_text FROM used_questions ORDER BY id DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [row[0] for row in rows]


async def _save_question(question_text: str) -> None:
    """ذخیره سوال جدید در تاریخچه."""
    await _init_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO used_questions (question_text) VALUES (?)",
            (question_text,),
        )
        await db.commit()


# ==========================================
#  ابزارهای پردازش JSON
# ==========================================

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


async def _get_unused_fallback(recent_qs: list[str]) -> dict:
    """انتخاب یک سوال از پیش‌فرض که در تاریخچه اخیر نباشد."""
    available = [q for q in FALLBACK_QUESTIONS if q["question"] not in recent_qs]
    if not available:
        # اگر همه سوالات استفاده شده بودند، تاریخچه را نادیده بگیر
        available = FALLBACK_QUESTIONS
    
    q = random.choice(available).copy()
    q["options"] = list(q["options"])
    await _save_question(q["question"])
    return q


# ==========================================
#  تولید سوال
# ==========================================

async def generate_question(category: Optional[str] = None) -> dict:
    """Generate a quiz question using AI with anti-repetition."""
    settings = get_settings()
    
    # پشتیبانی همزمان از کلیدهای Groq و DeepSeek
    api_key = getattr(settings, 'groq_api_key', '') or getattr(settings, 'deepseek_api_key', '')

    recent_qs = await _get_recent_questions(20)

    if not api_key:
        logger.info("کلید API تنظیم نشده — استفاده از سوالات آماده.")
        return await _get_unused_fallback(recent_qs)

    cat = category or random.choice(CATEGORIES)
    history_text = "\n".join([f"- {q}" for q in recent_qs]) if recent_qs else "هیچ سوالی تاکنون پرسیده نشده است."
    prompt = PROMPT_TEMPLATE.format(category=cat, history=history_text)

    try:
        from groq import AsyncGroq
        
        model_name = getattr(settings, 'groq_model', '') or "llama-3.3-70b-versatile"
        logger.info("کوییز با مدل: %s", model_name)

        client = AsyncGroq(api_key=api_key)

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
            temperature=0.5,  # کمی خلاقیت برای سوال جدید، اما بدون توهم
            max_tokens=600,
        )

        text = response.choices[0].message.content
        if not text:
            raise ValueError("AI returned empty")

        data = _extract_json(text)
        if data is None or not _validate_question(data):
            logger.warning("Invalid AI quiz JSON: %s", text[:200])
            raise ValueError("Invalid JSON structure")

        # ذخیره سوال جدید در تاریخچه
        new_question_text = str(data["question"]).strip()[:500]
        await _save_question(new_question_text)

        return {
            "question": new_question_text,
            "options": [str(o).strip()[:100] for o in data["options"]],
            "correct": int(data["correct"]),
            "explanation": str(data.get("explanation", "")).strip()[:400],
            "category": cat,
        }

    except Exception as e:
        logger.warning("AI question generation failed: %s — using fallback", e)
        return await _get_unused_fallback(recent_qs)
