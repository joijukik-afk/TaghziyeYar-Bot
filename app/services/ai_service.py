"""AI service with advanced context and system prompts."""

import logging
import time
from collections import defaultdict, deque
from typing import Optional
from groq import AsyncGroq
from app.config import get_settings

logger = logging.getLogger(__name__)

_RATE_WINDOW_SECONDS = 60
_RATE_MAX_REQUESTS = 15
_user_requests: dict[int, deque] = defaultdict(deque)

PREFERRED_MODELS = ["qwen/qwen3.8-27b", "llama-3.3-70b-versatile", "openai/gpt-oss-20b", "gemma2-9b-it"]

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

SYSTEM_PROMPT = """تو «تغذیه‌یار» هستی، یک دستیار هوشمند، مودب و همه‌فن‌حریف.
تخصص اصلی تو تغذیه و سلامت است، اما تو یک هوش مصنوعی جامع هستی.
اگر کاربر سوالی عمومی، علمی یا خبری پرسید، با دانش خودت به بهترین شکل جواب بده.

🚨 قوانین حیاتی (بسیار مهم):
1. اگر جواب سوالی را نمی‌دانی، حدس الکی نزن، اما سعی کن با دانش عمومی خودت کمک کنی.
2. تو حافظه چت داری. اگر کاربر به پیام قبلی اشاره کرد، متوجه شو.
3. اگر کاربر توی گروه روی پیام کسی ریپلای کرد، تو داری به اون شخص جواب می‌دی.
4. از تگ‌های HTML مثل <b>، <i>، <code> و <blockquote> استفاده کن. هرگز از مارک‌داون (**) استفاده نکن.
5. پاسخ‌هات باید کوتاه، مفید، و کاملاً انسانی باشن.

❌ قانون ممنوعیت سلام (بسیار مهم):
- تو فقط زمانی می‌تونی با «سلام» شروع کنی که کاربر توی پیام فعلی‌اش خودش «سلام» کرده باشه.
- اگر کاربر پیامی مثل «خوبی؟»، «چیکار می‌کنی؟» یا «یه سوال دارم» فرستاد که توش سلام نبود، تو نباید جوابت رو با «سلام» یا «درود» شروع کنی. مستقیم برو سر جواب.
"""

# 👇 پرامپت جدید و حرفه‌ای برای پاسخ‌های صوتی (با آوردن اسم کاربر)
VOICE_SYSTEM_PROMPT = (
    "تو یک دستیار صوتی فوق‌العاده باهوش، صمیمی و حرفه‌ای هستی. "
    "تو در حال صحبت کردن با کاربری هستی که نام او در ادامه به تو گفته می‌شود. "
    "🚨 بسیار مهم ۱: در همان جمله اول پاسخ خود، حتماً کاربر را با نامش صدا بزن (مثلاً: 'امیر جان، ...' یا 'کاربر عزیز، ...'). "
    "🚨 بسیار مهم ۲: پاسخ‌های تو باید کوتاه و مفید باشند (حداکثر ۳ تا ۴ جمله) چون قرار است به صدا تبدیل شوند. "
    "🚨 بسیار مهم ۳: هرگز جوابت رو با «سلام» شروع نکن (مگر اینکه کاربر سلام کرده باشه). "
    "🚨 بسیار مهم ۴: هرگز از ایموجی، کلمات انگلیسی، علامت‌های نگارشی عجیب یا فرمت‌بندی استفاده نکن. فقط متن فارسی روان و محاوره‌ای بنویس."
)

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
        if user_name: ctx.append(f"نام کاربری که با تو حرف میزنه: {user_name}")
        if user_profile_summary: ctx.append(f"اطلاعات سلامتی این کاربر:\n{user_profile_summary}")
        if ctx: messages.append({"role": "system", "content": "زمینه کاربر:\n" + "\n".join(ctx)})

        # 👇 اضافه کردن حافظه (۱۰ پیام آخر)
        if chat_history:
            for msg in chat_history[-10:]:
                role = msg.get("role", "user")
                content = (msg.get("content") or "")[:1000]
                if role in ("user", "assistant") and content: 
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})

        try:
            model_name = await self._pick_model()
            client = self._get_client()
            response = await client.chat.completions.create(
                model=model_name, messages=messages, temperature=0.6, max_tokens=2500, top_p=0.9
            )
            reply = (response.choices[0].message.content or "").strip()
            if not reply: raise ValueError("Empty response")
            return reply, "ok"
            
        except Exception as e:
            logger.error("AI API error: %s", e)
            try:
                fallback_model = "llama-3.3-70b-versatile"
                response = await client.chat.completions.create(model=fallback_model, messages=messages, temperature=0.6, max_tokens=2500)
                reply = (response.choices[0].message.content or "").strip()
                if reply: return reply, "ok"
            except Exception as e2:
                logger.error("Fallback AI error: %s", e2)
            
            return ("😔 یه لحظه مغزم هنگ کرد، دوباره بفرست.", "error")

    async def translate(self, text: str, target_language: str, user_id: int = 0) -> str:
        text = (text or "").strip()[:1500]
        if not text: return ""
        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed: return f"⏳ صبر کن ({wait} ثانیه)."
        if self.mock: return f"🤖 (ترجمه): {text}"

        messages = [{"role": "system", "content": f"You are a translator. Translate to '{target_language}'. Output only translation."}, {"role": "user", "content": text}]
        try:
            client = self._get_client()
            model_name = await self._pick_model()
            response = await client.chat.completions.create(model=model_name, messages=messages, temperature=0.1, max_tokens=2000)
            return (response.choices[0].message.content or "").strip() or "ترجمه‌ای دریافت نشد."
        except Exception: return "😔 خطا در ترجمه."

    async def transcribe_audio(self, file_path: str) -> str:
        if self.mock: return "متن آزمایشی"
        try:
            client = self._get_client()
            with open(file_path, "rb") as file:
                transcription = await client.audio.transcriptions.create(file=(file_path, file.read()), model="whisper-large-v3", response_format="text", language="fa")
            return str(transcription).strip()
        except Exception as e:
            logger.error(f"Whisper Error: {e}"); raise e

    async def analyze_image(self, image_base64: str, prompt: str, user_id: int = 0) -> str:
        if self.mock: return "🤖 (حالت آزمایشی)"
        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed: return f"⏳ صبر کن ({wait} ثانیه)."

        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]}]
        try:
            client = self._get_client()
            response = await client.chat.completions.create(model="qwen/qwen3.8-27b", messages=messages, temperature=0.7, max_tokens=1500)
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            return f"😔 خطا در تحلیل عکس:\n<code>{str(e)[:100]}</code>"

_ai_service: Optional[AIService] = None
def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None: _ai_service = AIService()
    return _ai_service
