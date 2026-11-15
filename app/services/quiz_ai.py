"""AI-powered quiz question generator with anti-repetition memory."""

import json
import logging
import random
import re
import asyncio
from typing import Optional

from groq import AsyncGroq
from app.config import get_settings
from app.database import repository as repo

logger = logging.getLogger(__name__)

# 👈 قفل سراسری برای جلوگیری از Race Condition
_quiz_lock = asyncio.Lock()

# 👈 Client مشترک
_groq_client: Optional[AsyncGroq] = None


def _get_groq_client() -> Optional[AsyncGroq]:
    global _groq_client
    settings = get_settings()
    api_key = getattr(settings, 'groq_api_key', '') or getattr(settings, 'deepseek_api_key', '')
    if not api_key:
        return None
    if _groq_client is None:
        _groq_client = AsyncGroq(api_key=api_key, timeout=30.0)
    return _groq_client


CATEGORIES = [
    "ویتامین‌ها و مواد معدنی", "پروتئین و عضله‌سازی", "کربوهیدرات و انرژی",
    "چربی‌های سالم", "فیبر و سلامت گوارش", "آب و هیدراتاسیون",
    "غذاهای ایرانی", "کاهش وزن اصولی", "تغذیه ورزشی",
    "باورهای اشتباه تغذیه", "ایمنی مواد غذایی", "خواندن برچسب مواد غذایی",
    "خواب و اشتها", "تغذیه گیاهی", "ریز‌مغذی‌ها",
]

PROMPT_TEMPLATE = """یک سوال چهارگزینه‌ای حرفه‌ای، علمی و کاملاً جدید درباره تغذیه بساز.

📌 دسته: {category}

✅ قوانین:
1. سوال باید علمی، دقیق و مبتنی بر دانش معتبر تغذیه باشه.
2. فارسی روان و طبیعی بنویس.
3. دقیقاً ۴ گزینه بده.
4. فقط یکی از گزینه‌ها درست باشه.
5. یه توضیح کوتاه (۱-۲ جمله) برای جواب درست بنویس.
6. پاسخ باید قطعی و علمی باشه.

🚨 قانون بسیار مهم (عدم تکرار):
سوال تو نباید شبیه به هیچ‌کدام از سوالات زیر باشد (نه از نظر مفهوم و نه از نظر گزینه‌ها). یک زاویه جدید و سوالی کاملاً متفاوت بساز:
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
    {"question": "کدام ویتامین به جذب آهن کمک می‌کند؟", "options": ["ویتامین A", "ویتامین C", "ویتامین D", "ویتامین K"], "correct": 1, "explanation": "ویتامین C جذب آهن را چند برابر می‌کند.", "category": "ویتامین‌ها و مواد معدنی"},
    {"question": "چند درصد بدن انسان از آب تشکیل شده؟", "options": ["۳۰٪", "۵۰٪", "۶۰٪", "۸۰٪"], "correct": 2, "explanation": "حدود ۶۰٪ وزن بدن آب است.", "category": "آب و هیدراتاسیون"},
    {"question": "در عدس‌پلو، منبع اصلی پروتئین کدام است؟", "options": ["برنج", "عدس", "کشمش", "زعفران"], "correct": 1, "explanation": "عدس سرشار از پروتئین گیاهی و فیبر است.", "category": "غذاهای ایرانی"},
    {"question": "فیبر روزانه چند گرم توصیه می‌شود؟", "options": ["۵-۱۰", "۱۵-۲۰", "۲۵-۳۵", "۵۰+"], "correct": 2, "explanation": "۲۵-۳۵ گرم فیبر روزانه توصیه می‌شود.", "category": "فیبر و سلامت گوارش"},
    {"question": "کدام برای انرژی سریع قبل از ورزش مناسب است؟", "options": ["چربی", "پروتئین", "کربوهیدرات", "فیبر"], "correct": 2, "explanation": "کربوهیدرات‌ها انرژی سریع فراهم می‌کنند.", "category": "تغذیه ورزشی"},
    {"question": "کدام ماده معدنی برای سلامت استخوان ضروری‌ست؟", "options": ["آهن", "روی", "کلسیم", "منیزیم"], "correct": 2, "explanation": "کلسیم ماده اصلی ساختار استخوان‌ها و دندان‌هاست.", "category": "ویتامین‌ها و مواد معدنی"},
    {"question": "کدام غذا منبع خوب پروتئین گیاهی‌ست؟", "options": ["عدس", "برنج", "سیب", "خیار"], "correct": 0, "explanation": "عدس سرشار از پروتئین گیاهی و فیبر است.", "category": "پروتئین و عضله‌سازی"},
    {"question": "هر گرم چربی چند کالری دارد؟", "options": ["۴", "۷", "۹", "۱۲"], "correct": 2, "explanation": "هر گرم چربی ۹ کالری دارد.", "category": "چربی‌های سالم"},
]


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    # 👈 پاکسازی کاراکترهای خاص فارسی که JSON را می‌شکنند
    text = text.replace("«", '"').replace("»", '"').replace("”", '"').replace("“", '"')
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


def _validate_question(data: dict) -> bool:
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
    if not data.get("question") or len(str(data["question"]).strip()) < 5:
        return False
    if not all(isinstance(o, str) and o.strip() for o in data["options"]):
        return False
    if not data.get("explanation") or len(str(data.get("explanation", "")).strip()) < 5:
        return False
    return True


async def _get_unused_fallback(recent_qs: list[str]) -> dict:
    recent_set = set(recent_qs)
    available = [q for q in FALLBACK_QUESTIONS if q["question"] not in recent_set]

    if not available:
        logger.warning("همه Fallback‌ها استفاده شده‌اند. چرخه جدید.")
        available = FALLBACK_QUESTIONS

    q = random.choice(available)
    result = {
        "question": q["question"],
        "options": list(q["options"]),
        "correct": q["correct"],
        "explanation": q["explanation"],
        "category": q["category"],
    }
    await repo.save_quiz_question(result["question"])
    return result


async def generate_question(category: Optional[str] = None) -> dict:
    # 👈 Lock برای جلوگیری از Race Condition
    async with _quiz_lock:
        settings = get_settings()
        client = _get_groq_client()

        recent_qs = await repo.get_recent_quiz_questions(limit=30)

        if client is None:
            logger.info("کلید API تنظیم نشده — استفاده از سوالات آماده.")
            return await _get_unused_fallback(recent_qs)

        cat = category or random.choice(CATEGORIES)
        history_text = "\n".join([f"- {q}" for q in recent_qs]) if recent_qs else "هیچ سوالی تاکنون پرسیده نشده است."
        prompt = PROMPT_TEMPLATE.format(category=cat, history=history_text)

        models_to_try = [getattr(settings, 'groq_model', ''), "qwen/qwen3.8-27b", "openai/gpt-oss-120b"]

        for model_name in models_to_try:
            if not model_name:
                continue
            try:
                logger.info("کوییز با مدل: %s", model_name)

                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "تو یک متخصص تغذیه هستی. فقط JSON خالص برگردان."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=800,
                )

                text = response.choices[0].message.content
                if not text:
                    continue

                data = _extract_json(text)
                if data is None or not _validate_question(data):
                    logger.warning("پاسخ AI معتبر نبود (مدل: %s)", model_name)
                    continue

                new_question_text = str(data["question"]).strip()[:500]
                await repo.save_quiz_question(new_question_text)

                return {
                    "question": new_question_text,
                    "options": [str(o).strip()[:100] for o in data["options"]],
                    "correct": int(data["correct"]),
                    "explanation": str(data["explanation"]).strip()[:400],
                    "category": cat,
                }

            except asyncio.TimeoutError:
                logger.warning("Timeout در مدل %s", model_name)
                continue
            except Exception as e:
                logger.warning("خطا در تولید با مدل %s: %s", model_name, e, exc_info=True)
                continue

        logger.warning("AI question generation failed — using fallback")
        return await _get_unused_fallback(recent_qs)
