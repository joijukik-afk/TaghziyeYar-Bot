"""سرویس دریافت و اعتبارسنجی پروکسی‌های رایگان از منابع گیت‌هاب"""

import asyncio
import logging
import time
from typing import List, Dict, Tuple
import httpx

logger = logging.getLogger(__name__)

# --- منابع معتبر و به‌روز گیت‌هاب برای دریافت پروکسی ---
# این منابع به صورت خودکار هر چند دقیقه یکبار آپدیت می‌شوند
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/proxyscrape/free-proxy-list/main/proxies/all/data.txt",
    "https://raw.githubusercontent.com/xyzs996/free-proxy-health-list/main/all.txt",
    "https://raw.githubusercontent.com/vAHiD55555/ProxyScraper/main/proxies.txt",
]

# تنظیمات تست
CHECK_TIMEOUT = 5.0  # حداکثر زمان برای تست هر پروکسی (ثانیه)
MAX_CONCURRENT_CHECKS = 50  # حداکثر تعداد تست همزمان برای جلوگیری از بلاک شدن
MIN_VALID_PROXIES = 30 # حداقل تعداد پروکسی سالمی که باید برگردانده شود

async def _fetch_source(client: httpx.AsyncClient, url: str) -> List[str]:
    """دریافت لیست خام پروکسی‌ها از یک منبع"""
    try:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        lines = resp.text.strip().split("\n")
        # پاکسازی خطوط (حذف فاصله‌های اضافی و خطوط خالی)
        return [line.strip() for line in lines if line.strip() and ":" in line]
    except Exception as e:
        logger.warning(f"Failed to fetch proxy source {url}: {e}")
        return []

async def _check_proxy(client: httpx.AsyncClient, proxy: str, semaphore: asyncio.Semaphore) -> Tuple[bool, str, float]:
    """تست یک پروکسی برای اطمینان از کارکرد آن"""
    async with semaphore:
        start_time = time.time()
        try:
            # استفاده از یک سایت سبک برای تست (httpbin)
            # اگر پروکسی کار کند، باید کد 200 برگرداند
            resp = await client.get(
                "https://httpbin.org/ip",
                proxies=proxy,
                timeout=CHECK_TIMEOUT
            )
            if resp.status_code == 200:
                latency = time.time() - start_time
                return True, proxy, latency
        except Exception:
            pass # پروکسی مرده یا کند است، نادیده گرفته می‌شود
        return False, proxy, 999.0

async def get_fast_proxies() -> List[Dict]:
    """تابع اصلی: جمع‌آوری، تست و بازگرداندن لیست پروکسی‌های سالم و سریع"""
    all_raw_proxies = set()

    # ۱. دریافت پروکسی‌ها از همه منابع به صورت موازی
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_source(client, url) for url in PROXY_SOURCES]
        results = await asyncio.gather(*tasks)
        
        for source_list in results:
            all_raw_proxies.update(source_list)

    if not all_raw_proxies:
        logger.warning("No raw proxies found from sources.")
        return []

    logger.info(f"Total unique raw proxies to check: {len(all_raw_proxies)}")

    # ۲. تست پروکسی‌ها به صورت موازی با محدودیت
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
    valid_proxies = []

    async with httpx.AsyncClient() as client:
        # فقط ۵۰۰ پروکسی اول را تست می‌کنیم تا زمان اجرا زیاد طول نکشد
        proxies_to_check = list(all_raw_proxies)[:500]
        check_tasks = [_check_proxy(client, p, semaphore) for p in proxies_to_check]
        
        # اجرای تست‌ها و جمع‌آوری نتایج
        for success, proxy, latency in await asyncio.gather(*check_tasks):
            if success:
                # فرمت‌دهی خروجی برای استفاده در پروژه
                if not proxy.startswith("http://") and not proxy.startswith("socks"):
                    proxy = f"http://{proxy}"
                valid_proxies.append({
                    "proxy": proxy,
                    "latency": round(latency, 2),
                    "type": "HTTP" if "http" in proxy else "SOCKS"
                })

    # ۳. مرتب‌سازی بر اساس سرعت (کمترین تاخیر) و محدود کردن تعداد
    valid_proxies.sort(key=lambda x: x["latency"])
    return valid_proxies[:MIN_VALID_PROXIES]
