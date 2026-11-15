"""AI service - Advanced context handling, strict formatting, and Voice support."""

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
_last_cleanup = time.time()

TEXT_MODEL_DEFAULT = "openai/gpt-oss-120b"  # 👈 مدل پیش‌فرض جایگزین
VISION_MODEL = "llama-3.2-11b-vision-preview"

PREFERRED_MODELS = [
    "openai/gpt-oss-120b",      # 👈 جایگزین رسمی Groq
    "qwen/qwen3.6-27b",         # 👈 جایگزین Qwen
    "openai/gpt-oss-20b",       # 👈 جایگزین مدل 8B
]

def _cleanup_old_rate_limits():
    global _last_cleanup
    if time.time() - _last_cleanup < 3600: return
    now = time.time()
    to_remove = [uid for uid, q in _user_requests.items() if not q or now - q[-1] > _RATE_WINDOW_SECONDS]
    for uid in to_remove: _user_requests.pop(uid, None)
    _last_cleanup = now

def _check_rate_limit(user_id: int) -> tuple[bool, int]:
    _cleanup_old_rate_limits()
    now = time.time()
    q = _user_requests[user_id]
    while q and now - q[0] > _RATE_WINDOW_SECONDS: q.popleft()
    if len(q) >= _RATE_MAX_REQUESTS:
        wait = int(_RATE_WINDOW_SECONDS - (now - q[0])) + 1
        return False, max(wait, 1)
    q.append(now)
    return True, 0

SYSTEM_PROMPT = """تو «تغذیه‌یار» هستی، یک دستیار هوشمند، حرفه‌ای، مودب و همه‌فن‌حریف.
تخصص اصلی تو تغذیه و سلامت است، اما تو یک هوش مصنوعی جامع و مسلط به تمام موضوعات (علمی، فناوری، خبری، اقتصادی و...) هستی.

🚨 قوانین حیاتی پردازش اطلاعات:
1. **اطلاعات وب:** اگر در پیام کاربر بخشی به نام «اطلاعات جستجو» یا «اطلاعات وب» وجود دارد، یعنی سیستم ما همین الان از اینترنت اطلاعاتی جمع‌آوری کرده است. تو **باید** بر اساس آن اطلاعات پاسخ دقیق بدهی.
2. **استخراج داده:** اگر در اطلاعات جستجو، عددی (مثل قیمت) یا کدی (مثل کد تخفیف) وجود دارد، حتماً آن را در پاسخ خود بگنجان.
3. **پشتیبان:** اگر اطلاعات جستجو خالی بود یا مشکل داشت، از دانش داخلی خودت استفاده کن، اما به کاربر بگو که این اطلاعات ممکن است به‌روز نباشد.
4. **ممنوعیت بهانه:** هرگز نگو "من دسترسی به اینترنت ندارم" یا "نمی‌توانم جستجو کنم". اگر چیزی پیدا نشد، بگو "جستجو کردم اما نتیجه دقیقی پیدا نکردم".

🎨 قوانین خروجی (بسیار مهم):
- پاسخ‌ها باید کاملاً فارسی، روان و با تگ‌های HTML نوشته شوند.
- تگ‌های مجاز: <b> (بولد)، <i> (ایتالیک)، <code> (کد یا عدد)، <blockquote> (نقل قول).
- هرگز از مارک‌داون تلگرام (مثل ** یا ##) استفاده نکن.
- پاسخ‌ها را با استفاده از بولت‌پوینت و خط جدید، خوانا و مرتب کن.

🧠 لحن و شخصیت:
- دوستانه، دقیق، علمی و انسانی.
- فقط اگر کاربر توی پیام فعلی سلام کرد، تو هم با سلام جواب بده.
"""

VOICE_SYSTEM_PROMPT = (
    "You are a smart and professional voice assistant. "
    "CRITICAL: Only natural Persian text. NO emojis, NO English words, NO markdown, NO asterisks, NO hashtags. Keep it short (2-3 sentences max). "
    "Do NOT start your answer with 'Salam' (Hello) unless the user greeted you first. "
    "Make your answer sound like a human speaking naturally."
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
        if self._client is None: self._client = AsyncGroq(api_key=self.api_key, timeout=30.0)
        return self._client

    async def _pick_model(self) -> str | None:
        if self._model_name: return self._model_name
        try:
            client = self._get_client()
            response = await client.models.list()
            available = [m.id for m in response.data]
        except Exception: available = []

        if self.requested_model and self.requested_model in available:
            self._model_name = self.requested_model; return self._model_name
        for m in PREFERRED_MODELS:
            if m in available:
                self._model_name = m; return self._model_name
        if available:
            self._model_name = available[0]; return self._model_name
        self._model_name = TEXT_MODEL_DEFAULT
        return self._model_name

    async def ask(self, user_message: str, user_name: str = "", user_profile_summary: str = "", chat_history: Optional[list[dict]] = None, user_id: int = 0, custom_system_prompt: Optional[str] = None) -> tuple[str, str]:
        user_message = (user_message or "").strip()[:6000]
        if not user_message: return "", "error"
        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed: return (f"⏳ صبر کن ({wait} ثانیه).", "rate_limited")
        if self.mock: return ("🤖 (حالت آزمایشی - AI فعال نیست)", "mock")

        sys_prompt = custom_system_prompt if custom_system_prompt else SYSTEM_PROMPT
        messages: list[dict] = [{"role": "system", "content": sys_prompt}]
        if user_name: messages.append({"role": "system", "content": f"نام کاربر: {user_name}"})
        if user_profile_summary: messages.append({"role": "system", "content": f"اطلاعات سلامتی و پروفایل کاربر:\n{user_profile_summary}"})
        if chat_history:
            for msg in chat_history[-6:]:
                role = msg.get("role", "user"); content = (msg.get("content") or "")[:800]
                if role in ("user", "assistant") and content: messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        try:
            client = self._get_client()
            model_name = await self._pick_model()
            logger.info(f"🤖 AI Using Model: {model_name}")
            response = await client.chat.completions.create(model=model_name, messages=messages, temperature=0.4, max_tokens=2500, top_p=0.9)
            reply = (response.choices[0].message.content or "").strip()
            if not reply: raise ValueError("پاسخ خالی از سرور AI")
            return reply, "ok"
        except Exception as e:
            logger.error("AI API error: %s", e, exc_info=True)
            return (f"🚨 خطای دقیق AI:\n<code>{str(e)[:300]}</code>", "error")

    async def translate(self, text: str, target_language: str, user_id: int = 0) -> str:
        text = (text or "").strip()[:1500]
        if not text: return ""
        if self.mock: return f"🤖 (ترجمه آزمایشی): {text}"

        messages = [
            {"role": "system", "content": f"You are a professional translator. Translate the text to '{target_language}'. Output ONLY the translation, no extra text."},
            {"role": "user", "content": text},
        ]
        try:
            client = self._get_client()
            response = await client.chat.completions.create(model=TEXT_MODEL_DEFAULT, messages=messages, temperature=0.1, max_tokens=2000)
            return (response.choices[0].message.content or "").strip() or "ترجمه ناموفق."
        except Exception as e:
            logger.error(f"Translation Error: {e}", exc_info=True)
            return f"🚨 خطای دقیق ترجمه:\n<code>{str(e)[:300]}</code>"

    async def transcribe_audio(self, file_path: str) -> str:
        if self.mock: return "متن آزمایشی"
        try:
            client = self._get_client()
            with open(file_path, "rb") as file:
                transcription = await client.audio.transcriptions.create(file=(file_path, file.read()), model="whisper-large-v3", response_format="text", language="fa")
            return str(transcription).strip()
        except Exception as e:
            logger.error(f"Whisper Error: {e}", exc_info=True)
            return f"🚨 خطای دقیق Whisper:\n<code>{str(e)[:300]}</code>"

    async def analyze_image(self, image_base64: str, prompt: str, user_id: int = 0) -> str:
        if self.mock: return "🤖 (حالت آزمایشی)"
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]}]
        try:
            client = self._get_client()
            response = await client.chat.completions.create(model=VISION_MODEL, messages=messages, temperature=0.7, max_tokens=1500)
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            logger.error(f"Vision Error: {e}", exc_info=True)
            return f"🚨 خطای دقیق Vision:\n<code>{str(e)[:300]}</code>"

_ai_service: Optional[AIService] = None
def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None: _ai_service = AIService()
    return _ai_service
