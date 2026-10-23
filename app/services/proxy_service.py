"""موتور جستجوی پروکسی MTProto (چندمنبعی و هوشمند)"""

import asyncio
import logging
import time
from typing import List, Dict
import httpx

logger = logging.getLogger(__name__)

# --- منابع معتبر و به‌روز (بر اساس جستجوهای انجام شده) ---
PROXY_SOURCES = [
    {
        "name": "tgmtproxy",
        "url": "https://tgmtproxy.github.io/mtproxy/proxies.txt",
        "update_interval_hours": 1,
        "priority": 1,
    },
    {
        "name": "dubblebyte",
        "url": "https://raw.githubusercontent.com/dubblebyte/free-mtproto-proxies/main/proxies.txt",
        "update_interval_hours": 8,
        "priority": 2,
    },
    {
        "name": "zakky8",
        "url": "https://zakky8.github.io/mtproto-proxy-pro/proxies.txt",
        "update_interval_hours": 6,
        "priority": 3,
    },
    {
        "name": "Grim1313",
        "url": "https://raw.githubusercontent.com/Grim1313/mtproto-for-telegram/master/all_proxies.txt",
        "update_interval_hours": 12,
        "priority": 4,
    },
]

# تنظیمات
MAX_PROXIES_TO_RETURN = 30
CACHE_TTL_SECONDS = 300  # 5 دقیقه کش برای جلوگیری از درخواست تکراری

# کش داخلی
_cache: Dict[str, dict] = {}
_cache_timestamp: float = 0

async def _fetch_source(client: httpx.AsyncClient, url: str) -> List[str]:
    """دریافت لیست خام پروکسی‌ها از یک منبع"""
    try:
        resp = await client.get(url, timeout=15.0)
        resp.raise_for_status()
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
        if p.startswith("tg://proxy?"):
            p = p.replace("tg://proxy?", "https://t.me/proxy?")
        elif p.startswith("https://telegram.me/proxy?"):
            p = p.replace("https://telegram.me/proxy?", "https://t.me/proxy?")
        if "t.me/proxy?" in p and p not in seen:
            seen.add(p)
            cleaned.append(p)
    return cleaned

def _prioritize_for_iran(proxies: List[str]) -> List[str]:
    """
    اولویت‌بندی هوشمند برای ایران:
    1. پروکسی‌هایی که پورت 443 دارند (بهترین گزینه برای عبور از DPI)
    2. پروکسی‌هایی که از FakeTLS استفاده می‌کنند (secret با ee شروع می‌شود)
    """
    def score(proxy: str) -> tuple:
        has_443 = "port=443" in proxy
        has_faketls = "secret=ee" in proxy
        # اولویت: (پورت 443, FakeTLS)
        return (not has_443, not has_faketls)
    
    return sorted(proxies, key=score)

async def get_best_proxies(limit: int = MAX_PROXIES_TO_RETURN) -> List[Dict]:
    """دریافت بهترین پروکسی‌ها از تمام منابع با کش هوشمند"""
    global _cache, _cache_timestamp
    
    # بررسی کش
    now = time.time()
    if _cache and (now - _cache_timestamp) < CACHE_TTL_SECONDS:
        logger.info("Returning cached proxies")
        return _cache.get("proxies", [])
    
    logger.info("Fetching fresh proxies from multiple sources...")
    all_proxies = []
    
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_source(client, source["url"]) for source in PROXY_SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res_list in results:
            if isinstance(res_list, list):
                all_proxies.extend(res_list)
    
    if not all_proxies:
        logger.warning("No proxies found from any source.")
        return []
    
    cleaned = _clean_and_normalize(all_proxies)
    if not cleaned:
        return []
    
    # اولویت‌بندی برای ایران
    prioritized = _prioritize_for_iran(cleaned)
    
    # محدود کردن تعداد
    selected = prioritized[:limit]
    
    result = [{"proxy": link} for link in selected]
    
    # ذخیره در کش
    _cache["proxies"] = result
    _cache_timestamp = now
    
    logger.info(f"Successfully retrieved {len(result)} MTProto proxies.")
    return result
