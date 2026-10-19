"""سرویس دریافت اخبار بین‌المللی، ترجمه با هوش مصنوعی و درج امضای متخصص"""

import logging
import random
import re
import html
import feedparser
from app.services.ai_service import get_ai_service
from app.config import get_settings

logger = logging.getLogger(__name__)

# 🌍 منابع خبری فوق‌العاده معتبر (WHO, NIH, Harvard, Medical News Today)
GLOBAL_RSS_FEEDS = [
    "https://www.who.int/rss-feeds/news-english.xml",
    "https://www.nih.gov/news-events/news-releases/rss.xml",
    "https://www.hsph.harvard.edu/news/feed/",
    "https://www.medicalnewstoday.com/rss/nutrition.xml",
]

def _clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    cleantext = html.unescape(cleantext)
    return re.sub(r'\s+', ' ', cleantext).strip()

async def get_global_magazine_news() -> tuple[str, str] | None:
    """دریافت جدیدترین خبر بین‌المللی، ترجمه و تنظیم آن به صورت مجله‌ای"""
    feed_url = random.choice(GLOBAL_RSS_FEEDS)
    
    try:
        feed = feedparser.parse(feed_url)
        if not feed.entries:
            return None

        # انتخاب جدیدترین خبر
        entry = feed.entries[0]
        title_en = _clean_html(entry.get("title", ""))
        summary_en = _clean_html(entry.get("summary", entry.get("description", "")))
        link = entry.get("link", "")

        # استخراج عکس اصلی خبر
        image_url = None
        if hasattr(entry, 'media_content') and entry.media_content:
            image_url = entry.media_content[0].get("url")
        
        if not image_url:
            image_url = "https://images.unsplash.com/photo-1490645935967-10de6ba17061?q=80&w=1024&auto=format&fit=crop"

        # 🧠 هوش مصنوعی: ترجمه و تبدیل به متن مجله‌ای
        ai = get_ai_service()
        prompt = (
            f"تو یک سردبیر مجله معتبر تغذیه هستی. این خبر انگلیسی را به فارسی روان، جذاب و علمی ترجمه کن.\n"
            f"ساختار خروجی باید دقیقاً این‌گونه باشد:\n"
            f"1. یک عنوان جذاب فارسی (با یک ایموجی مناسب)\n"
            f"2. متن خبر (حداکثر ۳ پاراگراف کوتاه و خوانا برای تلگرام)\n\n"
            f"عنوان اصلی: {title_en}\n"
            f"خلاصه خبر: {summary_en}\n\n"
            f"فقط و فقط متن فارسی را برگردان، هیچ توضیح اضافه‌ای نده."
        )
        
        ai_reply, _ = await ai.ask(user_message=prompt, user_id=0)
        
        if not ai_reply:
            return None

        # 🖋️ اضافه کردن لینک منبع و امضای شما
        settings = get_settings()
        final_text = (
            f"{ai_reply}\n\n"
            f"🔗 <a href='{link}'>مشاهده منبع اصلی</a>\n\n"
            f"{settings.signature}"  # 👈 این خط امضای شما را از config.py می‌خواند
        )
        
        return final_text, image_url

    except Exception as e:
        logger.warning("خطا در دریافت یا ترجمه خبر: %s", e)
        return None
