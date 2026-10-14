"""AI service — supports Groq / DeepSeek / any OpenAI-compatible API."""

import logging
import time
from collections import defaultdict, deque
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

_RATE_WINDOW_SECONDS = 60
_RATE_MAX_REQUESTS = 10

_user_requests: dict[int, deque] = defaultdict(deque)


def _check_rate_limit(user_id: int) -> tuple[bool, int]:
    now = time.time()
    q = _user_requests[user_id]
    while q and now - q[0] > _RATE_WINDOW_SECONDS:
        q.popleft()
    if len(q) >= _RATE_MAX_REQUESTS:
        wait = int(_RATE_WINDOW_SECONDS - (now - q[0])) + 1
        return False, max(wait, 1)
    q.append(now)
    return True, 0


SYSTEM_PROMPT = """تو «تغذیه‌یار» هستی، دستیار هوشمند تغذیه در یک گروه تلگرام فارسی.

وظایف تو:
- پاسخ دادن به سوالات تغذیه‌ای به فارسی روان و طبیعی
- پیشنهاد غذاهای ایرانی و سالم
- کمک به انتخاب وعده‌های غذایی
- محاسبه تقریبی ارزش غذایی (فقط تخمین)
- راهنمایی در مورد کاهش یا افزایش وزن به شکل ایمن

قوانین مهم:
1. پاسخ‌هایت کوتاه باشند (حداکثر ۴-۵ خط).
2. هیچ‌وقت خودت را پزشک یا متخصص تغذیه معرفی نکن.
3. برای شرایط پزشکی خاص حتماً بگو «با پزشک مشورت کن».
4. برای کودکان زیر ۱۸ سال توصیه رژیمی نده.
5. هیچ‌وقت ادعای قطعی نکن — بگو «تقریبی».
6. از ایموجی‌های کم و مناسب استفاده کن.
7. اگه سوال مبهمه، یه سوال تکمیلی کوتاه بپرس.
8. فارسی روان جواب بده.
9. اطلاعات پزشکی حساس رو تکرار نکن.
10. پاسخ‌هایت به فارسی و خوانا باشن.
"""


class AIService:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url
        self.model = settings.deepseek_model
        self.mock = settings.mock_mode or not self.api_key
        self._client: Optional[AsyncOpenAI] = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=30.0,
                max_retries=1,
            )
        return self._client

    async def ask(
        self,
        user_message: str,
        user_name: str = "",
        user_profile_summary: str = "",
        chat_history: Optional[list[dict]] = None,
        user_id: int = 0,
    ) -> tuple[str, str]:
        user_message = (user_message or "").strip()[:1500]
        if not user_message:
            return "", "error"

        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed:
                return (
                    f"⏳ خیلی سریع پیام می‌دی. {wait} ثانیه صبر کن.",
                    "rate_limited",
                )

        if self.mock:
            return (
                "🤖 (حالت آزمایشی — AI فعال نیست)\n"
                f"پیام تو: {user_message[:200]}\n\n"
                "برای فعال‌سازی، کلید API را در Render تنظیم کن.",
                "mock",
            )

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        ctx: list[str] = []
        if user_name:
            ctx.append(f"نام کاربر: {user_name}")
        if user_profile_summary:
            ctx.append(f"اطلاعات کاربر:\n{user_profile_summary}")
        if ctx:
            messages.append({
                "role": "system",
                "content": "زمینه کاربر:\n" + "\n".join(ctx),
            })

        if chat_history:
            for msg in chat_history[-6:]:
                role = msg.get("role", "user")
                content = (msg.get("content") or "")[:800]
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})

        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=600,
                top_p=0.95,
            )
            reply = (response.choices[0].message.content or "").strip()
            if not reply:
                return ("متأسفانه پاسخی دریافت نشد.", "error")
            return reply, "ok"
        except Exception as e:
            logger.warning("AI API error: %s", e)
            return (
                "😔 الان نمی‌تونم به سرور AI وصل بشم. چند دقیقه بعد دوباره تلاش کن.",
                "error",
            )


_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service
