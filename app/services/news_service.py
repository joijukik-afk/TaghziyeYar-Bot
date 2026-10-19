"""سرویس دریافت جدیدترین اخبار و مقالات تغذیه با ترجمه هوش مصنوعی"""

import logging
import random
import re
import html
from datetime import datetime
import httpx
import feedparser
from app.services.ai_service import get_ai_service
from app.config import get_settings

logger = logging.getLogger(__name__)

# 🌍 منابع خبری و علمی فوق‌العاده معتبر (همیشه به‌روز)
GLOBAL_RSS_FEEDS = [
    "https://www.news-medical.net/tag/feed/nutrition.aspx",      # اخبار تغذیه News-Medical
    "https://www.medicalnewstoday.com/rss/nutrition.xml",        # اخبار تغذیه Medical News Today
    "https://www.thelancet.com/collection/rss/001599",           # مجله لنست (تغذیه و متابولیسم)
    "http://feeds.nature.com/ejcn/rss/current",                  # مجله نیچر (تغذیه بالینی)
]

# 🛡️ منابع پشتیبان (اگر هیچ خبری نیامد، از این مقالات استفاده کن)
BACKUP_ARTICLES = [
    {
        "title": "اصول تغذیه سالم و متعادل: راهنمای جامع",
        "summary": "داشتن یک رژیم غذایی متعادل شامل مصرف متنوعی از مواد مغذی است. این راهنما به شما کمک می‌کند تا با انتخاب‌های هوشمندانه، سلامت خود را تضمین کنید.",
        "link": "https://www.who.int/news-room/fact-sheets/detail/healthy-diet"
    },
    {
        "title": "نقش پروتئین در عضله‌سازی و سلامت عمومی",
        "summary": "پروتئین یکی از سه درشت‌مغذی ضروری برای بدن است. مصرف کافی پروتئین به حفظ توده عضلانی، بهبود عملکرد ورزشی و تقویت سیستم ایمنی کمک می‌کند.",
        "link": "https://www.hsph.harvard.edu/nutritionsource/what-should-you-eat/protein/"
    },
    {
        "title": "اهمیت فیبر در رژیم غذایی و سلامت گوارش",
        "summary": "فیبر بخشی ضروری از یک رژیم سالم است. مصرف فیبر کافی به هضم غذا، کنترل قند خون و حفظ سلامت میکروبیوم روده کمک می‌کند.",
        "link": "https://www.mayoclinic.org/healthy-lifestyle/nutrition-and-healthy-eating/in-depth/fiber/art-20043983"
    }
]

def _clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    cleantext = html.unescape(cleantext)
    return re.sub(r'\s+', ' ', cleantext).strip()

def _format_date(entry) -> str:
    """استخراج و فرمت تاریخ انتشار خبر"""
    date_str = ""
    if hasattr(entry, 'published'):
        date_str = entry.published
    elif hasattr(entry, 'updated'):
        date_str = entry.updated
    
    if not date_str:
        return ""
    
    # تلاش برای فرمت کردن تاریخ
    try:
        # فرمت‌های رایج RSS
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                dt = datetime.strptime(date_str, fmt)
                return f"🗓 {dt.strftime('%d %B %Y')}"
            except ValueError:
                continue
        # اگر فرمت ناشناخته بود، خود رشته را برگردان
        return f"🗓 {date_str[:16]}"
    except Exception:
        return ""

async def get_global_magazine_news() -> tuple[str, str] | None:
    """جستجوی حرفه‌ای در منابع خبری و علمی برای یافتن جدیدترین مقاله"""
    
    # 🔄 منابع را شافل می‌کنیم تا هر بار یکی را امتحان کنیم
    feeds = list(GLOBAL_RSS_FEEDS)
    random.shuffle(feeds)
    
    for feed_url in feeds:
        try:
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
                continue 

            # انتخاب جدیدترین خبر
            entry = feed.entries[0]
            title_en = _clean_html(entry.get("title", ""))
            summary_en = _clean_html(entry.get("summary", entry.get("description", "")))
            link = entry.get("link", "")
            pub_date = _format_date(entry)

            if not summary_en or len(summary_en) < 30:
                continue

            # استخراج عکس
            image_url = None
            if hasattr(entry, 'media_content') and entry.media_content:
                image_url = entry.media_content[0].get("url")
            
            if not image_url:
                image_url = "https://images.unsplash.com/photo-1490645935967-10de6ba17061?q=80&w=1024&auto=format&fit=crop"

            # 🧠 هوش مصنوعی: ترجمه و تنظیم مجله‌ای
            ai = get_ai_service()
            prompt = (
                f"تو یک سردبیر مجله معتبر تغذیه هستی. این خبر انگلیسی را به فارسی روان، جذاب و علمی ترجمه کن.\n"
                f"ساختار خروجی باید دقیقاً این‌گونه باشد:\n"
                f"1. یک عنوان جذاب فارسی (با یک ایموجی مناسب)\n"
                f"2. متن خبر (حداکثر ۳ پاراگراف کوتاه و خوانا برای تلگرام)\n"
                f"3. یک نکته کلیدی و کاربردی در یک جمله\n\n"
                f"عنوان اصلی: {title_en}\n"
                f"خلاصه خبر: {summary_en}\n\n"
                f"فقط و فقط متن فارسی را برگردان، هیچ توضیح اضافه‌ای نده."
            )
            
            ai_reply, _ = await ai.ask(user_message=prompt, user_id=0)
            
            if not ai_reply:
                ai_reply = f"<b>{title_en}</b>\n\n{summary_en}\n\n(ترجمه هوش مصنوعی در حال حاضر در دسترس نیست)"

            settings = get_settings()
            final_text = (
                f"{ai_reply}\n\n"
                f"{pub_date}\n"
                f"🔗 <a href='{link}'>مشاهده منبع اصلی</a>\n\n"
                f"{settings.signature}"
            )
            
            return final_text, image_url

        except Exception as e:
            logger.warning(f"خطا در فید {feed_url}: {e}")
            continue

    # 🛡️ اگر همه منابع خبری خطا دادند، از مقالات پشتیبان استفاده کن
    logger.info("هیچ خبری دریافت نشد. استفاده از مقالات پشتیبان...")
    backup = random.choice(BACKUP_ARTICLES)
    settings = get_settings()
    final_text = (
        f"<b>{backup['title']}</b>\n\n"
        f"{backup['summary']}\n\n"
        f"🔗 <a href='{backup['link']}'>مشاهده منبع اصلی</a>\n\n"
        f"{settings.signature}"
    )
    return final_text, "https://images.unsplash.com/photo-1490645935967-10de6ba17061?q=80&w=1024&auto=format&fit=crop"
