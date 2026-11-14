"""AI service - Forces use of provided search context + Voice support."""

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

PREFERRED_MODELS = ["llama-3.3-70b-versatile", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]

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

SYSTEM_PROMPT = """تو «تغذیه‌یار» هستی، یک دستیار هوشمند و مفید.

🚨 قانون اکید پاسخ‌دهی:
اگر در پیام کاربر "اطلاعات جستجو" وجود دارد، تو **باید** از آن استفاده کنی و به سوال جواب بدهی.
اگر در اطلاعات جستجو **عددی** (مثل ۲۶۵,۰۰۰ یا 265000) وجود دارد که شبیه قیمت است، تو **باید** آن عدد را به کاربر بگویی. حتی اگر مطمئن نیستی دقیق است.
اگر در اطلاعات جستجو **کدی** (مثل SNAP50 یا OFF20) وجود دارد، آن را به کاربر بده.
هرگز نگو "من نمی‌توانم"، "دسترسی ندارم"، "به سایت مراجعه کن". تو اطلاعات را داری، از آن استفاده کن!

اگر هیچ اطلاعات جستجویی وجود نداشت، از دانش خودت استفاده کن اما بگو "تقریبی".
پاسخ فارسی، کوتاه و با HTML.
"""

VOICE_SYSTEM_PROMPT = (
    "You are a smart and professional voice assistant. "
    "CRITICAL: Only natural Persian text. NO emojis, NO English words, NO markdown. Keep it short (2-3 sentences). "
    "Do NOT start your answer with 'Salam' unless the user greeted you first."
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
            logger.warning("Model list error: %s", e); available = []

        if self.requested_model and self.requested_model in available:
            self._model_name = self.requested_model; return self._model_name
        for m in PREFERRED_MODELS:
            if m in available: self._model_name = m; return self._model_name
        if available: self._model_name = available[0]; return self._model_name
        self._model_name = self.requested_model or "llama-3.3-70b-versatile"
        return self._model_name

    async def ask(self, user_message: str, user_name: str = "", user_profile_summary: str = "", chat_history: Optional[list[dict]] = None, user_id: int = 0, custom_system_prompt: Optional[str] = None) -> tuple[str, str]:
        user_message = (user_message or "").strip()[:6000]
        if not user_message: return "", "error"

        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed: return (f"⏳ صبر کن ({wait} ثانیه).", "rate_limited")

        if self.mock: return ("🤖 (حالت آزمایشی)", "mock")

        sys_prompt = custom_system_prompt if custom_system_prompt else SYSTEM_PROMPT
        messages: list[dict] = [{"role": "system", "content": sys_prompt}]

        if user_name: messages.append({"role": "system", "content": f"نام کاربر: {user_name}"})
        if user_profile_summary: messages.append({"role": "system", "content": f"اطلاعات کاربر:\n{user_profile_summary}"})

        if chat_history:
            for msg in chat_history[-6:]:
                role = msg.get("role", "user")
                content = (msg.get("content") or "")[:800]
                if role in ("user", "assistant") and content: 
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})

        try:
            model_name = await self._pick_model()
            logger.info(f"🤖 Using model: {model_name}")
            client = self._get_client()
            response = await client.chat.completions.create(
                model=model_name, messages=messages, temperature=0.3, max_tokens=2500
            )
            reply = (response.choices[0].message.content or "").strip()
            return reply or "پاسخی دریافت نشد.", "ok"
        except Exception as e:
            logger.error("AI error: %s", e)
            return ("😔 خطا در اتصال به AI.", "error")

    async def translate(self, text: str, target_language: str, user_id: int = 0) -> str:
        text = (text or "").strip()[:1500]
        if not text: return ""
        if self.mock: return f"🤖 (ترجمه): {text}"
        messages = [{"role": "system", "content": f"Translate to '{target_language}'. Only output translation."}, {"role": "user", "content": text}]
        try:
            client = self._get_client()
            response = await client.chat.completions.create(model="llama-3.3-70b-versatile", messages=messages, temperature=0.1, max_tokens=2000)
            return (response.choices[0].message.content or "").strip() or "ترجمه ناموفق."
        except: return "😔 خطا در ترجمه."

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
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]}]
        try:
            client = self._get_client()
            response = await client.chat.completions.create(model="llama-3.2-11b-vision-preview", messages=messages, temperature=0.7, max_tokens=1500)
            return (response.choices[0].message.content or "").strip()
        except: return "😔 خطا در تحلیل عکس."

_ai_service: Optional[AIService] = None
def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None: _ai_service = AIService()
    return _ai_service
