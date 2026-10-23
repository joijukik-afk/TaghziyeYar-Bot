"""سرویس دریافت و اعتبارسنجی پروکسی‌های SOCKS5 برای ربات"""

import asyncio
import logging
import time
import httpx

logger = logging.getLogger(__name__)

# منابع معتبر SOCKS5
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt"
]

CHECK_TIMEOUT = 5.0
MAX_CONCURRENT_CHECKS = 30

async def _check_proxy(client: httpx.AsyncClient, proxy: str, semaphore: asyncio.Semaphore) -> dict | None:
    async with semaphore:
        start_time = time.time()
        proxy_url = f"socks5://{proxy.strip()}"
        try:
            # تست پروکسی با اتصال به سایت تلگرام
            resp = await client.get(
                "https://api.telegram.org",
                proxy=proxy_url,
                timeout=CHECK_TIMEOUT
            )
            if resp.status_code in (200, 404): # تلگرام معمولا 404 میده به روت، یعنی وصل شده
                latency = time.time() - start_time
                return {"proxy": proxy_url, "latency": round(latency, 2)}
        except Exception:
            pass
        return None

async def get_fast_proxies() -> list[dict]:
    all_raw_proxies = set()
    
    # ۱. گرفتن لیست‌ها
    async with httpx.AsyncClient() as client:
        for url in PROXY_SOURCES:
            try:
                resp = await client.get(url, timeout=10.0)
                for line in resp.text.strip().split("\n"):
                    if ":" in line and len(line) < 30:
                        all_raw_proxies.add(line.strip())
            except Exception as e:
                logger.warning(f"Failed to fetch {url}: {e}")

    if not all_raw_proxies:
        return []

    logger.info(f"Testing {len(all_raw_proxies)} proxies...")

    # ۲. تست آن‌ها
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
    valid_proxies = []

    # فقط ۱۰۰ تا اول را تست میکنیم که سریع باشه
    proxies_to_check = list(all_raw_proxies)[:100]
    
    async with httpx.AsyncClient() as client:
        tasks = [_check_proxy(client, p, semaphore) for p in proxies_to_check]
        results = await asyncio.gather(*tasks)
        
        for res in results:
            if res:
                valid_proxies.append(res)

    valid_proxies.sort(key=lambda x: x["latency"])
    return valid_proxies
