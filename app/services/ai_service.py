"""AI service — supports Groq / DeepSeek / any OpenAI-compatible API."""

import logging
import time
from collections import defaultdict, deque
from typing import Optional

from groq import AsyncGroq

from app.config import get_settings

logger = logging.getLogger(__name__)

_RATE_WINDOW_SECONDS = 60
_RATE_MAX_REQUESTS = 10

_user_requests: dict[int, deque] = defaultdict(deque)


PREFERRED_MODELS = [
    "openai/gpt-oss-120b",
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-20b",
    "gemma2-9b-it",
    "mixtral-8x7b-32768",
]


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

🎨 قوانین خروجی (مهم!):
تو خروجی HTML می‌دی که تلگرام رندر می‌کنه. فقط از این تگ‌ها استفاده کن:
<b>متن</b> — بولد
<i>متن</i> — ایتالیک
<code>متن</code> — کد درون‌خطی
<pre>متن</pre> — بلوک monospace (برای جدول!)
<blockquote>متن</blockquote> — نقل‌قول (پس‌زمینه خاکستری)
<a href="لینک">متن</a> — لینک

❌ ممنوع: markdown (`**`, `##`, `|`), جدول markdown, تگ‌های غیرمجاز مثل <div>, <table>, <tr>, <td>.

📊 ساخت جدول با <pre>:
حتماً از <pre>...</pre> برای جدول استفاده کن. چون فونت monospace داره و ستون‌ها هم‌تراز می‌شن.

برای جدول راست‌چین فارسی، از این الگو استفاده کن:

<blockquote>📊 عنوان جدول</blockquote>

<pre>
میوه            کالری
━━━━━━━━━━━━━━━━━━━━
🍎 سیب           52
🍌 موز           89
🍊 پرتقال        47
🍇 انگور         69
</pre>

⚠️ نکته مهم: توی <pre>، حتماً از فاصله‌های دقیق استفاده کن تا ستون‌ها هم‌تراز بشن. هر ردیف باید ۱۰-۱۵ کاراکتر فاصله بین اسم و مقدار داشته باشه.

📌 پاسخ‌های عادی:
- کوتاه (حداکثر ۴-۵ خط)
- فارسی روان
- از ایموجی‌های مناسب استفاده کن
- برای شرایط پزشکی خاص بگو «با پزشک مشورت کن»
- برای کودکان زیر ۱۸ سال توصیه رژیمی نده

📌 برای سوالات جدولی:
- از <pre> استفاده کن
- عنوان رو در <blockquote> بذار
- خط جداکننده (━━━ یا ───) بین هدر و ردیف‌ها بذار
- ستون‌ها رو با فاصله هم‌تراز کن
"""


class AIService:
    def __init__(self):
        settings = get_settings()
        self.api_key = settings.deepseek_api_key
        self.requested_model = settings.deepseek_model or ""
        self.mock = settings.mock_mode or not self.api_key
        self._client: Optional[AsyncGroq] = None
        self._model_name: Optional[str] = None

    def _get_client(self) -> AsyncGroq:
        if self._client is None:
            self._client = AsyncGroq(api_key=self.api_key)
        return self._client

    async def _pick_model(self) -> str | None:
        if self._model_name:
            return self._model_name

        try:
            client = self._get_client()
            response = await client.models.list()
            available = [m.id for m in response.data]
            logger.info("مدل‌های موجود Groq: %s", ", ".join(available[:10]))
        except Exception as e:
            logger.warning("خطا در دریافت لیست مدل‌ها: %s", e)
            available = []

        if self.requested_model and self.requested_model in available:
            self._model_name = self.requested_model
            return self._model_name

        for m in PREFERRED_MODELS:
            if m in available:
                self._model_name = m
                return self._model_name

        if available:
            self._model_name = available[0]
            return self._model_name

        self._model_name = self.requested_model or "openai/gpt-oss-120b"
        return self._model_name

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
            model_name = await self._pick_model()
            if not model_name:
                return ("😔 مدل AI در دسترس نیست.", "error")

            logger.info("استفاده از مدل: %s", model_name)

            client = self._get_client()
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.7,
                max_tokens=1500,
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
