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

# بهترین مدل‌های متنی و پردازش زبان طبیعی در Groq
PREFERRED_MODELS = [
    "llama-3.3-70b-versatile", 
    "qwen/qwen3.8-27b", 
    "openai/gpt-oss-20b",
    "gemma2-9b-it"
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

# 👇 پرامپت بسیار قدرتمند برای جستجو و پاسخ‌دهی در همه موضوعات
SYSTEM_PROMPT = """تو «تغذیه‌یار» هستی، یک دستیار هوشمند، حرفه‌ای، مودب و همه‌فن‌حریف.
تخصص اصلی تو تغذیه و سلامت است، اما تو یک هوش مصنوعی جامع و مسلط به تمام موضوعات (علمی، فناوری، خبری، اقتصادی و...) هستی.

🚨 قوانین حیاتی پردازش اطلاعات:
1. **اطلاعات وب:** اگر در پیام کاربر بخشی به نام «اطلاعات جستجو» یا «اطلاعات وب» وجود دارد، یعنی سیستم ما همین الان از اینترنت اطلاعاتی جمع‌آوری کرده است. تو **باید** بر اساس آن اطلاعات پاسخ دقیق بدهی.
2. **استخراج داده:** اگر در اطلاعات جستجو، عددی (مثل قیمت) یا کدی (مثل کد تخفیف) وجود دارد، حتماً آن را در پاسخ خود بگنجان.
3. **پشتیبان:** اگر اطلاعات جستجو خالی بود یا مشکل داشت، از دانش داخلی خودت استفاده کن، اما به کاربر بگو که این اطلاعات ممکن است به‌روز نباشد.
4. **ممنوعیت بهانه:** هرگز نگو "من دسترسی به اینترنت ندارم" یا "نمی‌توانم جستجو کنم". تو در حال حاضر اطلاعات را در اختیار داری یا داری از دانشت استفاده می‌کنی. اگر چیزی پیدا نشد، بگو "جستجو کردم اما نتیجه دقیقی پیدا نکردم".

🎨 قوانین خروجی (بسیار مهم):
- پاسخ‌ها باید کاملاً فارسی، روان و با تگ‌های HTML نوشته شوند.
- تگ‌های مجاز: <b> (بولد)، <i> (ایتالیک)، <code> (کد یا عدد)، <blockquote> (نقل قول).
- هرگز از مارک‌داون تلگرام (مثل ** یا ##) استفاده نکن.
- پاسخ‌ها را با استفاده از بولت‌پوینت و خط جدید، خوانا و مرتب کن.

🧠 لحن و شخصیت:
- دوستانه، دقیق، علمی و انسانی.
- فقط اگر کاربر توی پیام فعلی سلام کرد، تو هم با سلام جواب بده.
"""

# 👇 پرامپت مخصوص پاسخ‌های صوتی (بدون ایموجی و علامت‌های اضافی)
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
            logger.warning("Model list error: %s", e); available = []

        if self.requested_model and self.requested_model in available:
            self._model_name = self.requested_model; return self._model_name
        for m in PREFERRED_MODELS:
            if m in available: self._model_name = m; return self._model_name
        if available: self._model_name = available[0]; return self._model_name
        
        self._model_name = self.requested_model or "llama-3.3-70b-versatile"
        return self._model_name

    async def ask(
        self, 
        user_message: str, 
        user_name: str = "", 
        user_profile_summary: str = "", 
        chat_history: Optional[list[dict]] = None, 
        user_id: int = 0, 
        custom_system_prompt: Optional[str] = None
    ) -> tuple[str, str]:
        
        user_message = (user_message or "").strip()[:6000] # فضای کافی برای اطلاعات Tavily
        if not user_message: return "", "error"

        if user_id:
            allowed, wait = _check_rate_limit(user_id)
            if not allowed: return (f"⏳ صبر کن ({wait} ثانیه).", "rate_limited")

        if self.mock: return ("🤖 (حالت آزمایشی - AI فعال نیست)", "mock")

        # انتخاب پرامپت (اگر برای ویس بود، پرامپت ویس، اگر برای سرچ بود، پرامپت جستجوگر)
        sys_prompt = custom_system_prompt if custom_system_prompt else SYSTEM_PROMPT
        messages: list[dict] = [{"role": "system", "content": sys_prompt}]

        # اضافه کردن کانتکست
        if user_name: 
            messages.append({"role": "system", "content": f"نام کاربر: {user_name}"})
        if user_profile_summary: 
            messages.append({"role": "system", "content": f"اطلاعات سلامتی و پروفایل کاربر:\n{user_profile_summary}"})

        # اضافه کردن حافظه (چت‌های قبلی)
        if chat_history:
            for msg in chat_history[-6:]: # ۶ پیام آخر برای سرعت بیشتر
                role = msg.get("role", "user")
                content = (msg.get("content") or "")[:800]
                if role in ("user", "assistant") and content: 
                    messages.append({"role": role, "content": content})

        # اضافه کردن پیام نهایی کاربر (که ممکن است حاوی اطلاعات Tavily باشد)
        messages.append({"role": "user", "content": user_message})

        try:
            model_name = await self._pick_model()
            logger.info(f"🤖 AI Using Model: {model_name}")
            
            client = self._get_client()
            response = await client.chat.completions.create(
                model=model_name, 
                messages=messages, 
                temperature=0.4, # دمای متعادل برای دقت + کمی خلاقیت در نوشتن
                max_tokens=2500,
                top_p=0.9
            )
            
            reply = (response.choices[0].message.content or "").strip()
            if not reply: 
                raise ValueError("پاسخ خالی از سرور AI")
                
            return reply, "ok"
            
        except Exception as e:
            logger.error("AI API error: %s", e)
            
            # تلاش با مدل پشتیبان
            try:
                fallback_model = "llama-3.3-70b-versatile"
                response = await client.chat.completions.create(
                    model=fallback_model, messages=messages, temperature=0.4, max_tokens=2500
                )
                reply = (response.choices[0].message.content or "").strip()
                if reply: return reply, "ok"
            except Exception as e2:
                logger.error("Fallback AI error: %s", e2)
            
            return ("😔 یه خطای فنی پیش اومد، دوباره بفرست.", "error")

    async def translate(self, text: str, target_language: str, user_id: int = 0) -> str:
        text = (text or "").strip()[:1500]
        if not text: return ""
        if self.mock: return f"🤖 (ترجمه آزمایشی): {text}"
        
        messages = [
            {"role": "system", "content": f"You are a professional translator. Translate the text to '{target_language}'. Output ONLY the translation, no extra text."}, 
            {"role": "user", "content": text}
        ]
        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile", messages=messages, temperature=0.1, max_tokens=2000
            )
            return (response.choices[0].message.content or "").strip() or "ترجمه ناموفق."
        except: 
            return "😔 خطا در ترجمه."

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
        if self.mock: return "🤖 (حالت آزمایشی)"
        
        messages = [
            {
                "role": "user", 
                "content": [
                    {"type": "text", "text": prompt}, 
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }
        ]
        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model="llama-3.2-11b-vision-preview", messages=messages, temperature=0.7, max_tokens=1500
            )
            return (response.choices[0].message.content or "").strip()
        except: 
            return "😔 خطا در تحلیل عکس."

_ai_service: Optional[AIService] = None
def get_ai_service() -> AIService:
    global _ai_service
    if _ai_service is None: 
        _ai_service = AIService()
    return _ai_service
