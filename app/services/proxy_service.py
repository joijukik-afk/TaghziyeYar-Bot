"""موتور جستجو، اعتبارسنجی و امتیازدهی پروکسی (نسخه سریع و بدون تایم‌اوت)"""

import asyncio
import logging
import time
from typing import List, Dict, Optional
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

# منابع معتبر
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/http.txt",
]

# تنظیمات بهینه‌شده برای سرعت بالا
CHECK_TIMEOUT = 3.0  # کاهش زمان تست به ۳ ثانیه
MAX_CONCURRENT_CHECKS = 100 # تست ۱۰۰ پروکسی همزمان
MAX_PROXIES_TO_CHECK = 100 # حداکثر ۱۰۰ پروکسی رو تست میکنیم
TEST_URL = "https://api.telegram.org"

class ProxyPool:
    def __init__(self):
        self.proxies: Dict[str, dict] = {}

    async def get_best_proxies(self, limit: int = 30) -> List[Dict]:
        try:
            # 👇 محدودیت زمانی کل فرآیند (حداکثر ۲۰ ثانیه) تا Render کرش نکنه
            return await asyncio.wait_for(self._fetch_and_test(), timeout=20.0)
        except asyncio.TimeoutError:
            logger.warning("Proxy fetching timed out.")
            return []
        except Exception as e:
            logger.error(f"Error in get_best_proxies: {e}")
            return []

    async def _fetch_and_test(self) -> List[Dict]:
        raw_proxies = set()
        
        # ۱. دریافت از منابع
        async with httpx.AsyncClient() as client:
            for url in PROXY_SOURCES:
                try:
                    resp = await client.get(url, timeout=5.0)
                    if resp.status_code == 200:
                        for line in resp.text.strip().split("\n"):
                            line = line.strip()
                            if ":" in line and len(line) < 30:
                                proxy_url = f"socks5://{line}" if "socks5" in url else f"http://{line}"
                                raw_proxies.add(proxy_url)
                except Exception:
                    pass
        
        if not raw_proxies:
            return []

        proxies_to_check = list(raw_proxies)[:MAX_PROXIES_TO_CHECK]
        
        # ۲. تست پروکسی‌ها
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
        valid_proxies = []

        async def check(proxy_url: str):
            async with semaphore:
                start = time.time()
                try:
                    async with httpx.AsyncClient(proxy=proxy_url, timeout=CHECK_TIMEOUT) as client:
                        resp = await client.get(TEST_URL)
                        if resp.status_code in (200, 404):
                            latency = time.time() - start
                            valid_proxies.append({
                                "proxy": proxy_url,
                                "latency": round(latency, 2),
                                "success_rate": 100.0
                            })
                except Exception:
                    pass

        await asyncio.gather(*(check(p) for p in proxies_to_check))
        
        # ۳. مرتب‌سازی بر اساس سرعت
        valid_proxies.sort(key=lambda x: x["latency"])
        return valid_proxies[:limit]

# ساخت یک نمونه سراسری
proxy_pool = ProxyPool()
