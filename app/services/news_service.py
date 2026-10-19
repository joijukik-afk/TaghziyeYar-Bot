"""سرویس دریافت اخبار بین‌المللی، ترجمه با هوش مصنوعی و درج امضای متخصص"""

import logging
import random
import re
import html
import httpx
import feedparser
from app.services.ai_service import get_ai_service
from app.config import get_settings

logger = logging.getLogger(__name__)

# 🌍 منابع خبری فوق‌العاده معتبر
GLOBAL_RSS_FEEDS = [
    "https://www.medicalnewstoday.com/rss/nutrition.xml", # معمولاً دسترسی راحت‌تری داره
    "https://www.who.int/rss-feeds/news-english.xml",
    "https://www.hsph.harvard.edu/news/feed/",
    "https://www.sciencedaily.com/rss/health_medicine/nutrition.xml"
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
    
    # 🔄 تلاش با منابع مختلف تا یکی جواب بده
    random.shuffle(GLOBAL_RSS_FEEDS)
    
    for feed_url in GLOBAL_RSS_FEEDS:
        try:
            # 🛡️ جعل هویت مرورگر برای جلوگیری از بلاک شدن
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
            }
            
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                response = await client.get(feed_url, headers=headers)
                response.raise_for_status()
                
            feed = feedparser.parse(response.content)
            if not feed.entries:
                logger.warning(f"هیچ خبری در فید {feed_url} پیدا نشد.")
                continue # برو سراغ فید بعدی

            # انتخاب جدیدترین خبر
            entry = feed.entries[0]
            title_en = _clean_html(entry.get("title", ""))
            summary_en = _clean_html(entry.get("summary", entry.get("description", "")))
            link = entry.get("link", "")

            # اگر خلاصه خیلی کوتاه بود یا خالی بود، برو خبر بعدی
            if not summary_en or len(summary_en) < 50:
                continue

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
            
            # اگر هوش مصنوعی جواب نداد، خود متن انگلیسی را با یک پیام واضح بفرست
            if not ai_reply:
                ai_reply = f"<b>{title_en}</b>\n\n{summary_en}\n\n(ترجمه هوش مصنوعی در حال حاضر در دسترس نیست)"

            settings = get_settings()
            final_text = (
                f"{ai_reply}\n\n"
                f"🔗 <a href='{link}'>مشاهده منبع اصلی</a>\n\n"
                f"{settings.signature}"
            )
            
            return final_text, image_url

        except Exception as e:
            logger.warning(f"خطا در دریافت یا پردازش فید {feed_url}: {e}")
            continue # اگر این فید خطا داد، سراغ فید بعدی برو

    # اگر همه فیدها خطا دادند
    return None
