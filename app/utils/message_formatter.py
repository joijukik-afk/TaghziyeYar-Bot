"""Helper to add a signature to bot messages."""

import logging
from app.config import get_settings

logger = logging.getLogger(__name__)

# 👇 امضای جدید ربات (بدون اسم متخصص)
def with_signature(text: str) -> str:
    """Adds a stylish signature to the end of the text."""
    if not text:
        return text
        
    settings = get_settings()
    brand = getattr(settings, "bot_display_name", "تغذیه‌یار")
    
    # اگر متن از قبل امضا داشت، دوباره اضافه نکن
    if "🌱" in text[-20:]:
        return text
        
    signature = f"\n\n🌱 <b>{brand}</b> | دستیار هوشمند شما"
    
    # فقط به متن اضافه می‌کنیم (چون تلگرام HTML رو ساپورت می‌کنه)
    return text + signature
