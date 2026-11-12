"""AI service — supports Groq / DeepSeek / any OpenAI-compatible API."""

import logging
import time
import random
from collections import defaultdict, deque
from typing import Optional
from groq import AsyncGroq
from app.config import get_settings

logger = logging.getLogger(__name__)

_RATE_WINDOW_SECONDS = 60
_RATE_MAX_REQUESTS = 15
_user_requests: dict[int, deque] = defaultdict(deque)

PREFERRED_MODELS = ["qwen/qwen3.8-27b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "gemma2-9b-it"]

# 👇 جواب‌های جایگزین در صورتی که سرور هوش مصنوعی کلاً قطع باشد
FALLBACK_RESPONSES = [
    "سلام! 👋 من همینجام، یه لحظه مغزم هنگ کرد! 😅 دوباره پیامت رو بفرست.",
    "🌱 جالبه! ولی الان درگیر پردازش یه سری اطلاعاتم. می‌تونی یه بار دیگه سوالت رو بپرسی؟",
    "متوجه شدم! ارتباطم با سرور اصلی یه لحظه قطع شد. چی بود؟ دوباره بگو تا دقیق جواب بدم.",
    "🤖 یه لحظه صبر کن، دارم اطلاعات رو آپدیت می‌کنم. لطفاً دوباره بفرست.",
    "💧 یه نکته تغذیه‌ای بگم تا سرور درست بشه: نوشیدن آب کافی باعث افزایش متابولیسم می‌شه! (حالا دوباره پیامت رو بفرست 😅)"
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

# 👇 پرامپت جدید و بسیار قوی (دستور به ربات که به هر چیزی جواب بده)
SYSTEM_PROMPT = """تو «تغذیه‌یار» هستی، یک دستیار هوشمند، خوش‌برخورد، پرانرژی و همه‌فن‌حریف.
تخصص اصلی تو تغذیه و سلامت است، اما تو یک هوش مصنوعی جامع هستی.

🚨 قانون طلایی (بسیار مهم!):
تو باید به **هر پیامی** که کاربر می‌فرستد جواب بدهی! حتی اگر پیام فقط یک کلمه (مثل "سلام")، یک حرف، یا یک ایموجی باشد.
هرگز نگو "من نمی‌توانم جواب بدهم". تو همیشه آنلاین هستی و همیشه یک جواب دوستانه، مفید یا بامزه داری.

📌 نحوه رفتار:
- اگر کاربر فقط گفت "سلام"، تو با خوش‌رویی سلام کن و بپرس چطور می‌توانی کمکش کنی.
- اگر سوال عمومی، علمی یا خبری پرسید، با دانش خودت به بهترین شکل جواب بده.
- از تگ‌های HTML مثل <b>، <i>، <code> و <blockquote> استفاده کن. هرگز از مارک‌داون (**) استفاده نکن.
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
        if self._client is None: self._client = AsyncGroq(api_key=self.api_key)
        return self._client

    async def _pick_model(self) -> str | None:
        if self._model_name: return self._model_name
        try:
            client = self._get_client()
            response = await client.models.list()
            available = [m.id for m in response.data]
        except Exception as e:
            logger.warning("خطا در دریافت لیست مدل‌ها: %s", e); available = []

        if self.requested_model and self.requested_model in available:
            self._model_name = self.requested_model; return self._model_name
        for m in PREFERRED_MODELS:
            if m in available: self._model_name = m; return self._model_name
        if available: self._model_name = available[0]; return self._model_name
        
        self._model_name = self.requested_model or "llama-3.3-70b-versatile"
        return self._model_name

    async def ask(self, user_message: str, user_name: str = "", user_profile_summary: str = "", chat_history: Optional[list[dict]] = None, user_id: int = 0, custom_system_prompt: Optional[str] = None) -> tuple[str, str]:
        user_message = (user_message or "").strip()[:2500]
        if not user_message: return "", "error"

        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed: return (f"⏳ خیلی سریع پیام می‌دی. {wait} ثانیه صبر کن.", "rate_limited")

        if self.mock: return ("🤖 (حالت آزمایشی)", "mock")

        sys_prompt = custom_system_prompt if custom_system_prompt else SYSTEM_PROMPT
        messages: list[dict] = [{"role": "system", "content": sys_prompt}]

        ctx: list[str] = []
        if user_name: ctx.append(f"نام کاربر: {user_name}")
        if user_profile_summary: ctx.append(f"اطلاعات سلامتی:\n{user_profile_summary}")
        if ctx: messages.append({"role": "system", "content": "زمینه کاربر:\n" + "\n".join(ctx)})

        if chat_history:
            for msg in chat_history[-6:]:
                role = msg.get("role", "user")
                content = (msg.get("content") or "")[:800]
                if role in ("user", "assistant") and content: messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})

        try:
            model_name = await self._pick_model()
            client = self._get_client()
            # دما را روی 0.7 گذاشتیم تا ربات خلاقیت و گرمی بیشتری در جواب دادن داشته باشه
            response = await client.chat.completions.create(
                model=model_name, messages=messages, temperature=0.7, max_tokens=2500, top_p=0.9
            )
            reply = (response.choices[0].message.content or "").strip()
            
            if not reply: raise ValueError("Empty response")
            return reply, "ok"
            
        except Exception as e:
            logger.error("AI API error with primary model: %s", e)
            
            # تلاش مجدد با مدل پشتیبان (اگر مدل اول ارور داد)
            try:
                fallback_model = "llama-3.3-70b-versatile"
                response = await client.chat.completions.create(
                    model=fallback_model, messages=messages, temperature=0.7, max_tokens=2500
                )
                reply = (response.choices[0].message.content or "").strip()
                if reply: return reply, "ok"
            except Exception as e2:
                logger.error("Fallback AI API error: %s", e2)
            
            # 👇 اگر هر دو مدل قطع بودن، یک جواب از پیش نوشته‌شده می‌دیم تا کاربر ناراضی نشه
            return random.choice(FALLBACK_RESPONSES), "fallback"

    async def translate(self, text: str, target_language: str, user_id: int = 0) -> str:
        text = (text or "").strip()[:1500]
        if not text: return ""
        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed: return f"⏳ صبر کن ({wait} ثانیه)."
        if self.mock: return f"🤖 (ترجمه): {text}"

        translation_prompt = f"You are a translator. Translate to '{target_language}'. Output only translation."
        messages = [{"role": "system", "content": translation_prompt}, {"role": "user", "content": text}]

        try:
            model_name = await self._pick_model()
            client = self._get_client()
            response = await client.chat.completions.create(model=model_name, messages=messages, temperature=0.1, max_tokens=2000)
            return (response.choices[0].message.content or "").strip() or "ترجمه‌ای دریافت نشد."
        except Exception as e:
            logger.warning("Translate error: %s", e); return "😔 خطا در ترجمه."

    async def transcribe_audio(self, file_path: str) -> str:
        if self.mock: return "متن آزمایشی"
        try:
            client = self._get_client()
            with open(file_path, "rb") as file:
                transcription = await client.audio.transcriptions.create(
                    file=(file_path, file.read()), model="whisper-large-v3", response_format="text", language="fa" 
                )
            return str(transcription).strip()
        except Exception as e:
            logger.error(f"Whisper Error: {e}"); raise e

    async def analyze_image(self, image_base64: str, prompt: str, user_id: int = 0) -> str:
        if self.mock:
            return "🤖 (حالت آزمایشی) - عکس دریافت شد اما AI فعال نیست."

        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed: return f"⏳ خیلی سریع پیام می‌دی. {wait} ثانیه صبر کن."

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                    }
                ]
            }
        ]

        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model="qwen/qwen3.8-27b", 
                messages=messages,
                temperature=0.7,
                max_tokens=1500,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"Vision API error: {e}")
            return f"😔 متأسفانه در تحلیل تصویر خطایی پیش آمد.\n\nعلت خطا:\n<code>{str(e)[:200]}</code>"

_ai_service: Optional[AIService] = None
def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None: _ai_service = AIService()
    return _ai_service
