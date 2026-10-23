"""موتور جستجو، اعتبارسنجی و امتیازدهی پروکسی برای KOMA"""

import asyncio
import logging
import time
from typing import List, Dict, Optional
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

# --- منابع معتبر و به‌روز (بر اساس جستجوهای انجام شده) ---
PROXY_SOURCES = [
    # منبع ۱: لیست به‌روز شده هر ۵ دقیقه (HTTP, SOCKS4, SOCKS5)
    "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/http.txt",
    "https://raw.githubusercontent.com/databay-labs/free-proxy-list/master/socks5.txt",
    # منبع ۲: لیست به‌روز شده هر ۳۰ دقیقه
    "https://raw.githubusercontent.com/proxy-free/free-proxy-list/main/socks5.txt",
    "https://raw.githubusercontent.com/proxy-free/free-proxy-list/main/http.txt",
    # منبع ۳: لیست تخصصی SOCKS5 (تست‌شده)
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
]

# تنظیمات اعتبارسنجی
CHECK_TIMEOUT = 8.0  # حداکثر زمان برای تست هر پروکسی
MAX_CONCURRENT_CHECKS = 50 # تعداد تست همزمان
MIN_SUCCESS_RATE = 0.5 # حداقل نرخ موفقیت برای ماندن در لیست
MIN_LATENCY_THRESHOLD = 5.0 # حداکثر تأخیر مجاز (ثانیه)
TEST_URL = "https://api.telegram.org" # آدرس تست (تلگرام)

class ProxyPool:
    def __init__(self):
        self.proxies: Dict[str, dict] = {} # {proxy_url: {latency, success_rate, last_checked}}
        self._lock = asyncio.Lock()

    async def update_pool(self):
        """به‌روزرسانی استخر پروکسی‌ها"""
        logger.info("Starting proxy pool update...")
        raw_proxies = await self._fetch_all_sources()
        if not raw_proxies:
            logger.warning("No raw proxies fetched.")
            return

        # تست و اعتبارسنجی
        tested_proxies = await self._validate_proxies(raw_proxies)
        
        async with self._lock:
            # به‌روزرسانی استخر با پروکسی‌های جدید
            for proxy_url, data in tested_proxies.items():
                if proxy_url in self.proxies:
                    # به‌روزرسانی نرخ موفقیت
                    old_data = self.proxies[proxy_url]
                    # فرمول EWMA (میانگین متحرک وزنی) برای نرخ موفقیت
                    old_data["success_rate"] = (old_data["success_rate"] * 0.7) + (1.0 * 0.3)
                    old_data["latency"] = data["latency"]
                    old_data["last_checked"] = time.time()
                else:
                    self.proxies[proxy_url] = data
            
            # حذف پروکسی‌هایی که عملکرد ضعیفی دارند
            to_remove = [
                p for p, d in self.proxies.items()
                if d["success_rate"] < MIN_SUCCESS_RATE or d["latency"] > MIN_LATENCY_THRESHOLD
            ]
            for p in to_remove:
                del self.proxies[p]
            
            logger.info(f"Proxy pool updated. Active proxies: {len(self.proxies)}")

    async def _fetch_all_sources(self) -> List[str]:
        """دریافت پروکسی‌ها از تمام منابع"""
        all_proxies = set()
        async with httpx.AsyncClient() as client:
            tasks = [client.get(url, timeout=15.0) for url in PROXY_SOURCES]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            for url, resp in zip(PROXY_SOURCES, responses):
                if isinstance(resp, Exception):
                    logger.warning(f"Failed to fetch {url}: {resp}")
                    continue
                
                lines = resp.text.strip().split("\n")
                for line in lines:
                    line = line.strip()
                    if ":" in line and len(line) < 30: # فیلتر ساده
                        # تشخیص نوع پروکسی
                        if line.startswith("socks5://"):
                            all_proxies.add(line)
                        else:
                            all_proxies.add(f"http://{line}")
        return list(all_proxies)

    async def _validate_proxies(self, proxies: List[str]) -> Dict[str, dict]:
        """اعتبارسنجی پروکسی‌ها با تست اتصال به تلگرام"""
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
        valid_proxies = {}
        
        async def check(proxy_url: str):
            async with semaphore:
                start_time = time.time()
                try:
                    async with httpx.AsyncClient(proxy=proxy_url, timeout=CHECK_TIMEOUT) as client:
                        resp = await client.get(TEST_URL)
                        # تلگرام معمولا 404 برمی‌گرداند، اما اگر اتصال برقرار شود، یعنی پروکسی کار می‌کند
                        if resp.status_code in (200, 404):
                            latency = time.time() - start_time
                            return proxy_url, {"latency": latency, "success_rate": 1.0, "last_checked": time.time()}
                except Exception:
                    pass
                return proxy_url, None

        tasks = [check(p) for p in proxies]
        results = await asyncio.gather(*tasks)
        
        for proxy_url, data in results:
            if data:
                valid_proxies[proxy_url] = data
                
        return valid_proxies

    async def get_best_proxies(self, limit: int = 30) -> List[Dict]:
        """دریافت بهترین پروکسی‌ها بر اساس امتیاز (ترکیب تأخیر و نرخ موفقیت)"""
        async with self._lock:
            if not self.proxies:
                await self.update_pool()
                if not self.proxies:
                    return []

            # مرتب‌سازی بر اساس تأخیر (کمتر بهتر) و نرخ موفقیت (بیشتر بهتر)
            sorted_proxies = sorted(
                self.proxies.items(),
                key=lambda item: (item[1]["success_rate"], -item[1]["latency"]),
                reverse=True
            )
            
            result = []
            for proxy_url, data in sorted_proxies[:limit]:
                result.append({
                    "proxy": proxy_url,
                    "latency": round(data["latency"], 2),
                    "success_rate": round(data["success_rate"] * 100, 1)
                })
            return result

# نمونه Singleton
proxy_pool = ProxyPool()
