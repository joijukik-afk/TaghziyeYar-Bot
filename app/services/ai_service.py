"""AI service — supports Groq / DeepSeek / any OpenAI-compatible API."""

import logging
import time
from collections import defaultdict, deque
from typing import Optional

from groq import AsyncGroq

from app.config import get_settings

logger = logging.getLogger(__name__)

_RATE_WINDOW_SECONDS = 60
_RATE_MAX_REQUESTS = 15 # 👈 افزایش محدودیت به ۱۵ درخواست در دقیقه برای کاربران فعال

_user_requests: dict[int, deque] = defaultdict(deque)

PREFERRED_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "gemma2-9b-it",
    "llama-3.3-70b-versatile"
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

# 👇 پرامپت جدید و فوق‌العاده قوی برای شخصیت ربات
SYSTEM_PROMPT = """تو «تغذیه‌یار» هستی، یک دستیار هوشمند، فوق‌العاده باهوش، مودب و همه‌فن‌حریف در تلگرام.
تخصص اصلی تو تغذیه، سلامت و تناسب اندام است، اما تو یک هوش مصنوعی همه‌چیزدان هستی و می‌توانی در صورت نیاز به سوالات عمومی (علمی، فناوری، برنامه‌نویسی و...) هم پاسخ دقیق بدهی.

🚨 قوانین حیاتی (بسیار مهم):
1. هرگز اطلاعات غلط یا توهمی نده. اگر کالری یا عدد دقیقی را نمی‌دانی، بگو «تقریبی» است.
2. هیچ‌گاه توصیه پزشکی خطرناک (مثل تجویز دارو یا دوز خودسرانه ویتامین) نکن. برای بیماری‌های خاص (دیابت، کلیه، بارداری) حتماً به پزشک ارجاع بده.
3. اگر از تو سوالی پرسیدند که هیچ ربطی به تخصصت نداشت، سعی کن با دانش عمومی خودت جواب بدهی (چون تو یک دستیار هوشمند جامع هستی). فقط اگر سوال بسیار تخصصی و خارج از توان تو بود، مودبانه عذرخواهی کن.

🎨 قوانین خروجی (بسیار مهم!):
تو خروجی HTML می‌دی که تلگرام رندر می‌کنه. فقط از این تگ‌ها استفاده کن:
<b>متن</b> — بولد (برای تاکید)
<i>متن</i> — ایتالیک
<code>متن</code> — کد درون‌خطی
<pre>متن</pre> — بلوک monospace (برای جدول یا کدهای طولانی)
<blockquote>متن</blockquote> — نقل‌قول (برای نکات مهم)
<a href="لینک">متن</a> — لینک

❌ هرگز از مارک‌داون تلگرام (مثل ** یا ##) استفاده نکن! فقط و فقط HTML.
❌ تگ‌های غیرمجاز مثل <div>, <table>, <tr>, <td> ممنوع است.

📌 لحن تو:
- دوستانه، صمیمی، انگیزه‌بخش و حرفه‌ای.
- از ایموجی‌های مناسب استفاده کن.
- پاسخ‌ها را خوانا و مرتب بنویس (از خط جدید و بولت‌پوینت استفاده کن).
"""

class AIService:
    def __init__(self):
        settings = get_settings()
        self.api_key = getattr(settings, 'groq_api_key', '') or getattr(settings, 'deepseek_api_key', '')
        self.requested_model = getattr(settings, 'groq_model', '') or getattr(settings, 'deepseek_model', '')
        self.mock = settings.mock_mode or not self.api_key
        self._client: Optional[AsyncGroq] = None
        self._model_name: Optional[str] = None

    def _get_client(self) -> AsyncGroq:
        if self._client is None:
            self._client = AsyncGroq(api_key=self.api_key)
        return self._client

    async def _pick_model(self) -> str | None:
        if self._model_name: return self._model_name
        try:
            client = self._get_client()
            response = await client.models.list()
            available = [m.id for m in response.data]
        except Exception as e:
            logger.warning("خطا در دریافت لیست مدل‌ها: %s", e)
            available = []

        # اگر مدل درخواستی کاربر موجود بود
        if self.requested_model and self.requested_model in available:
            self._model_name = self.requested_model
            return self._model_name

        # انتخاب بهترین مدل از لیست پیشنهادی
        for m in PREFERRED_MODELS:
            if m in available:
                self._model_name = m
                return self._model_name

        # اگر هیچکدام نبود، اولین مدل موجود
        if available:
            self._model_name = available[0]
            return self._model_name

        # حالت پشتیبان (Fallback)
        self._model_name = self.requested_model or "llama-3.3-70b-versatile"
        return self._model_name

    async def ask(
        self,
        user_message: str,
        user_name: str = "",
        user_profile_summary: str = "",
        chat_history: Optional[list[dict]] = None,
        user_id: int = 0,
        custom_system_prompt: Optional[str] = None,
    ) -> tuple[str, str]:
        user_message = (user_message or "").strip()[:2000]
        if not user_message: return "", "error"

        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed: 
                return (f"⏳ خیلی سریع پیام می‌دی. {wait} ثانیه صبر کن.", "rate_limited")

        if self.mock:
            return (
                "🤖 (حالت آزمایشی — AI فعال نیست)\n"
                f"پیام تو: {user_message[:200]}\n\n"
                "برای فعال‌سازی، کلید API را در تنظیمات سرور قرار بده.", 
                "mock"
            )

        # استفاده از پرامپت اختصاصی (مثل جستجوگر یا مترجم) در صورت وجود
        sys_prompt = custom_system_prompt if custom_system_prompt else SYSTEM_PROMPT
        messages: list[dict] = [{"role": "system", "content": sys_prompt}]

        ctx: list[str] = []
        if user_name: 
            ctx.append(f"نام کاربر: {user_name}")
        if user_profile_summary: 
            ctx.append(f"اطلاعات سلامتی کاربر:\n{user_profile_summary}")
        
        if ctx: 
            messages.append({"role": "system", "content": "زمینه کاربر:\n" + "\n".join(ctx)})

        # اضافه کردن تاریخچه چت (حداکثر ۶ پیام آخر برای سرعت بیشتر)
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
                return ("😔 مدل هوش مصنوعی در دسترس نیست.", "error")

            client = self._get_client()
            response = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0.5, # 👈 تنظیم دما روی 0.5 برای ایجاد تعادل بین خلاقیت و دقت
                max_tokens=2500,
                top_p=0.9,
            )
            reply = (response.choices[0].message.content or "").strip()
            return reply, "ok" if reply else ("متأسفانه پاسخی دریافت نشد.", "error")
            
        except Exception as e:
            logger.error("AI API error: %s", e)
            return ("😔 الان نمی‌تونم به سرور هوش مصنوعی وصل بشم. لطفاً چند دقیقه بعد دوباره تلاش کن.", "error")

    async def translate(self, text: str, target_language: str, user_id: int = 0) -> str:
        text = (text or "").strip()[:1500]
        if not text: return ""
        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed: return f"⏳ خیلی سریع پیام می‌دی. {wait} ثانیه صبر کن."
        if self.mock: return f"🤖 (ترجمه آزمایشی به {target_language}): {text}"

        translation_prompt = f"You are a professional translator. Translate the text to the language code '{target_language}'. Only output the translated text. Do not add any explanation."
        messages = [{"role": "system", "content": translation_prompt}, {"role": "user", "content": text}]

        try:
            model_name = await self._pick_model()
            client = self._get_client()
            response = await client.chat.completions.create(
                model=model_name, messages=messages, temperature=0.1, max_tokens=2000
            )
            return (response.choices[0].message.content or "").strip() or "ترجمه‌ای دریافت نشد."
        except Exception as e:
            logger.warning("AI Translate API error: %s", e)
            return "😔 خطا در اتصال به سرور ترجمه."

    async def transcribe_audio(self, file_path: str) -> str:
        if self.mock: return "این یک متن آزمایشی است."
        try:
            client = self._get_client()
            with open(file_path, "rb") as file:
                transcription = await client.audio.transcriptions.create(
                    file=(file_path, file.read()),
                    model="whisper-large-v3",
                    response_format="text",
                    language="fa" 
                )
            return str(transcription).strip()
        except Exception as e:
            logger.error(f"Whisper Transcription Error: {e}")
            raise e


_ai_service: Optional[AIService] = None

def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService()
    return _ai_service
