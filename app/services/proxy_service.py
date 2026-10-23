"""موتور دریافت و تست لحظه‌ای پروکسی MTProto (بهینه برای ایران)"""

import asyncio
import logging
import httpx
import urllib.parse
from typing import List, Dict

logger = logging.getLogger(__name__)

# بهترین و به‌روزترین منابع گیت‌هاب
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/Grim1313/mtproto-for-telegram/master/all_proxies.txt",
    "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt",
    "https://raw.githubusercontent.com/MTProto-Proxy/MTProto-Proxy/main/proxies.txt",
]

async def _fetch_source(client: httpx.AsyncClient, url: str) -> List[str]:
    try:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        return [line.strip() for line in resp.text.split("\n") if line.strip() and "t.me/proxy" in line]
    except Exception:
        return []

async def _test_proxy_alive(server: str, port: int) -> bool:
    """تست فوق سریع برای زنده بودن پورت پروکسی"""
    try:
        # تست اتصال به سوکت سرور
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(server, port), 
            timeout=3.0
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False

async def get_best_proxies(limit: int = 20) -> List[Dict]:
    logger.info("Fetching and testing proxies...")
    all_links = []
    
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_source(client, url) for url in PROXY_SOURCES]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                all_links.extend(res)

    if not all_links:
        return []

    # فیلتر کردن و استخراج اطلاعات
    valid_proxies = []
    seen = set()
    
    for link in all_links:
        if link.startswith("tg://proxy?"):
            link = link.replace("tg://proxy?", "https://t.me/proxy?")
        
        if link in seen or "t.me/proxy?" not in link:
            continue
        seen.add(link)

        # پارس کردن لینک برای گرفتن سرور و پورت
        parsed = urllib.parse.urlparse(link)
        query = urllib.parse.parse_qs(parsed.query)
        
        server = query.get("server", [""])[0]
        port_str = query.get("port", ["0"])[0]
        secret = query.get("secret", [""])[0]

        if not server or not port_str.isdigit():
            continue

        port = int(port_str)
        
        # فقط پورت ۴۴۳ و FakeTLS رو اولویت بده (بهترین برای ایران)
        if port == 443 or secret.startswith("ee"):
            valid_proxies.append({
                "link": link,
                "server": server,
                "port": port,
                "is_faketls": secret.startswith("ee")
            })

    # مرتب‌سازی: پورت ۴۴۳ و FakeTLS اول باشن
    valid_proxies.sort(key=lambda x: (not x["is_faketls"], x["port"] != 443))

    # تست همزمان ۴۰ تا از بهترین‌ها
    proxies_to_test = valid_proxies[:40]
    
    async def check_and_return(p):
        is_alive = await _test_proxy_alive(p["server"], p["port"])
        if is_alive:
            return p
        return None

    logger.info(f"Testing {len(proxies_to_test)} proxies in parallel...")
    tested_results = await asyncio.gather(*(check_and_return(p) for p in proxies_to_test))
    
    # جمع‌آوری پروکسی‌های زنده
    alive_proxies = [p for p in tested_results if p is not None]
    
    logger.info(f"Found {len(alive_proxies)} alive proxies.")
    
    return [{"proxy": p["link"]} for p in alive_proxies[:limit]]
