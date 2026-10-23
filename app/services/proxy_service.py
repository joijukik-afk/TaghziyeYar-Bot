"""موتور جستجوی پروکسی MTProto از منابع معتبر و به‌روز گیت‌هاب"""

import asyncio
import logging
import random
from typing import List, Dict
import httpx

logger = logging.getLogger(__name__)

# --- منابع معتبر و به‌روز برای دریافت پروکسی MTProto ---
# این منابع به صورت خودکار تست و آپدیت می‌شوند
PROXY_SOURCES = [
    # منبع ۱: به‌روزرسانی هر ساعت (بسیار معتبر)
    "https://raw.githubusercontent.com/tgmtproxy/telegram-mtproto-proxy-list/main/proxies.txt",
    # منبع ۲: به‌روزرسانی هر ۱۲ ساعت (تست‌شده)
    "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt",
    # منبع ۳: به‌روزرسانی هر ۱۲ ساعت (فرمت‌های مختلف)
    "https://raw.githubusercontent.com/Grim1313/mtproto-for-telegram/master/all_proxies.txt",
    # منبع ۴: خروجی JSON با تست Fake-TLS (به‌روزرسانی منظم)
    "https://raw.githubusercontent.com/Yagami200/free-mtproto-proxies/main/data/proxies.json",
]

async def _fetch_source(client: httpx.AsyncClient, url: str) -> List[str]:
    """دریافت لیست خام پروکسی‌ها از یک منبع"""
    try:
        resp = await client.get(url, timeout=15.0)
        resp.raise_for_status()
        
        # اگر منبع JSON بود
        if url.endswith(".json"):
            data = resp.json()
            proxies = []
            # استخراج لینک‌ها از ساختار JSON (بسته به فرمت منبع)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        proxies.append(item)
                    elif isinstance(item, dict):
                        # تلاش برای پیدا کردن لینک در دیکشنری
                        for key in ["link", "url", "proxy", "tg_link"]:
                            if key in item:
                                proxies.append(item[key])
                                break
            return proxies
        
        # اگر منبع متنی بود
        lines = resp.text.strip().split("\n")
        return [line.strip() for line in lines if line.strip() and ("tg://" in line or "t.me/proxy" in line)]
    except Exception as e:
        logger.warning(f"Failed to fetch proxy source {url}: {e}")
        return []

def _clean_and_normalize(proxies: List[str]) -> List[str]:
    """پاکسازی، نرمال‌سازی و حذف تکراری‌ها"""
    cleaned = []
    seen = set()
    
    for p in proxies:
        p = p.strip()
        if not p:
            continue
        
        # نرمال‌سازی لینک‌ها به فرمت استاندارد https://t.me/proxy?...
        if p.startswith("tg://proxy?"):
            p = p.replace("tg://proxy?", "https://t.me/proxy?")
        elif p.startswith("https://telegram.me/proxy?"):
            p = p.replace("https://telegram.me/proxy?", "https://t.me/proxy?")
        
        # اطمینان از اینکه لینک معتبر است
        if "t.me/proxy?" in p and p not in seen:
            seen.add(p)
            cleaned.append(p)
    
    return cleaned

async def get_best_proxies(limit: int = 30) -> List[Dict]:
    """دریافت بهترین پروکسی‌ها از تمام منابع به صورت موازی"""
    logger.info("Fetching MTProto proxies from multiple sources...")
    
    all_proxies = []
    
    async with httpx.AsyncClient() as client:
        # دریافت همزمان از همه منابع
        tasks = [_fetch_source(client, url) for url in PROXY_SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res_list in results:
            if isinstance(res_list, list):
                all_proxies.extend(res_list)
    
    if not all_proxies:
        logger.warning("No proxies found from any source.")
        return []

    # پاکسازی و نرمال‌سازی
    cleaned_proxies = _clean_and_normalize(all_proxies)
    
    if not cleaned_proxies:
        logger.warning("No valid MTProto proxy links found after cleaning.")
        return []

    # به هم ریختن برای تنوع و انتخاب تصادفی از بین جدیدترین‌ها
    random.shuffle(cleaned_proxies)
    
    # محدود کردن تعداد خروجی
    selected = cleaned_proxies[:limit]
    
    result = []
    for proxy_link in selected:
        result.append({
            "proxy": proxy_link,
            "source": "MTProto"
        })
    
    logger.info(f"Successfully retrieved {len(result)} MTProto proxies.")
    return result
