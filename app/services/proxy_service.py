"""موتور دریافت پروکسی MTProto (سریع، بدون تست و بدون دردسر)"""

import asyncio
import logging
from typing import List, Dict
import httpx

logger = logging.getLogger(__name__)

# بهترین و به‌روزترین منابع موجود که هر ۱ تا ۱۲ ساعت آپدیت میشن
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/MTProto-Proxy/MTProto-Proxy/main/proxies.txt",
    "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt",
    "https://raw.githubusercontent.com/Grim1313/mtproto-for-telegram/master/all_proxies.txt",
]

async def _fetch_source(client: httpx.AsyncClient, url: str) -> List[str]:
    try:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        lines = resp.text.strip().split("\n")
        return [line.strip() for line in lines if line.strip() and ("tg://" in line or "t.me/proxy" in line)]
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return []

async def get_best_proxies(limit: int = 30) -> List[Dict]:
    logger.info("Fetching fresh MTProto proxies...")
    all_links = []
    
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_source(client, url) for url in PROXY_SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res_list in results:
            if isinstance(res_list, list):
                all_links.extend(res_list)

    if not all_links:
        return []

    cleaned = set()
    for p in all_links:
        # تبدیل به فرمت کلیک‌پذیر
        if p.startswith("tg://proxy?"):
            p = p.replace("tg://proxy?", "https://t.me/proxy?")
        
        # فیلتر کردن: فقط پروکسی‌هایی که برای ایران عالی‌اند (پورت 443 و FakeTLS)
        if "t.me/proxy?" in p:
            if "port=443" in p or "secret=ee" in p:
                cleaned.add(p)
            else:
                # بقیه رو هم به عنوان گزینه پشتیبان اضافه میکنیم
                cleaned.add(p)

    # اولویت دادن به FakeTLS (secret=ee) و پورت 443
    final_list = sorted(list(cleaned), key=lambda x: (0 if "secret=ee" in x and "port=443" in x else 1))

    return [{"proxy": link} for link in final_list[:limit]]
