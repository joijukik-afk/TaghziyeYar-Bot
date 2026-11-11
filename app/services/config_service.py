"""موتور قدرتمند دریافت کانفیگ V2Ray (۳ لایه، ضد خطا، همیشه پاسخگو)"""

import asyncio
import hashlib
import json
import logging
import random
import re
import urllib.parse
from typing import List, Optional
import httpx

logger = logging.getLogger(__name__)

# منابع بسیار قوی (روزانه هزاران کانفیگ جدید می‌ذارن)
TOP_SOURCES = [
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/DukeMehdi/FreeList-V2ray-Configs/refs/heads/main/Configs/All-DukeMehdi-Configs.txt",
    "https://raw.githubusercontent.com/liMilCo/v2r/main/best.txt",
    "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/sub.txt",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/mix",
    "https://raw.githubusercontent.com/Soroushmirzaei/telegram-configs-collector/main/protocols/reality",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/All_Configs_Sub.txt",
]

SENT_HASHES_FILE = "sent_configs.json"
CACHE_POOL_FILE = "config_cache_pool.json"

def _load_json(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_json(path: str, data: list):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Save error {path}: {e}")

async def _fetch_source(client: httpx.AsyncClient, url: str) -> List[str]:
    try:
        resp = await client.get(url, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            return []
        # استخراج تمام پروتکل‌های ممکن
        return re.findall(r'(?:vless|vmess|trojan|ss|ssr|hysteria2?|tuic)://[^\s]+', resp.text, re.IGNORECASE)
    except Exception as e:
        logger.warning(f"Fetch warning ({url}): {e}")
        return []

async def _test_tcp_alive(host: str, port: int) -> bool:
    """تست سریع TCP (حداکثر ۲ ثانیه) برای اطمینان از زنده بودن سرور"""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=2.0)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False

def _parse_host_port(config: str) -> Optional[tuple]:
    try:
        if config.startswith("vmess://"): return None
        parsed = urllib.parse.urlparse(config)
        if parsed.hostname and parsed.port:
            return parsed.hostname, parsed.port
    except Exception:
        pass
    return None

async def _filter_alive(configs: List[str]) -> List[str]:
    """تست همزمان و فیلتر کردن کانفیگ‌های زنده"""
    alive = []
    sem = asyncio.Semaphore(50) # ۵۰ تست همزمان
    
    async def check(c):
        hp = _parse_host_port(c)
        if not hp: return c
        host, port = hp
        async with sem:
            if await _test_tcp_alive(host, port):
                return c
        return None

    results = await asyncio.gather(*(check(c) for c in configs))
    for r in results:
        if r: alive.append(r)
    return alive

def _prioritize(configs: List[str]) -> List[str]:
    """اولویت‌بندی: Reality اول، TLS دوم"""
    def score(c):
        cl = c.lower()
        if "security=reality" in cl: return 0
        if "security=tls" in cl or "port=443" in cl: return 1
        return 2
    return sorted(configs, key=score)

async def get_fresh_configs(limit: int = 15) -> List[str]:
    sent_hashes = set(_load_json(SENT_HASHES_FILE))
    cache_good = _load_json(CACHE_POOL_FILE)
    
    # اگر تعداد هش‌ها خیلی زیاد شد (بیشتر از ۱۰۰۰۰)، حافظه رو ریست کن
    if len(sent_hashes) > 10000:
        logger.info("Memory full. Resetting sent hashes...")
        sent_hashes.clear()
        _save_json(SENT_HASHES_FILE, [])

    raw_configs = []
    
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_source(client, url) for url in TOP_SOURCES]
        results = await asyncio.gather(*tasks)
        for res in results:
            raw_configs.extend(res)

    # حذف تکراری‌ها و کانفیگ‌های ارسال شده
    unique_new = []
    new_hashes = set()
    seen_now = set()
    
    for c in raw_configs:
        h = hashlib.md5(c.encode()).hexdigest()
        if h not in sent_hashes and h not in seen_now:
            unique_new.append(c)
            new_hashes.add(h)
            seen_now.add(h)

    # تست زنده بودن
    alive_configs = await _filter_alive(unique_new)
    
    # اولویت‌بندی
    prioritized = _prioritize(alive_configs)
    
    final_selection = prioritized[:limit]
    
    # 🚀 **سیستم نجات ۱:** اگر جدید نبود، از Cache بده
    if len(final_selection) < limit and cache_good:
        logger.info("Using backup cache to fill the gap...")
        random.shuffle(cache_good)
        for c in cache_good:
            if len(final_selection) >= limit: break
            if c not in final_selection:
                final_selection.append(c)

    # 🚀 **سیستم نجات ۲:** اگر Cache هم خالی بود، از کانفیگ‌های خام (بدون تست) بده
    if len(final_selection) < limit and raw_configs:
        logger.info("Using raw configs as last resort...")
        random.shuffle(raw_configs)
        for c in raw_configs:
            if len(final_selection) >= limit: break
            if c not in final_selection:
                final_selection.append(c)

    # ذخیره در حافظه
    if final_selection:
        sent_hashes.update(new_hashes)
        _save_json(SENT_HASHES_FILE, list(sent_hashes))
        
        # آپدیت Cache (حداکثر ۱۰۰ تا نگه داریم)
        updated_cache = list(set(final_selection + cache_good))[:100]
        _save_json(CACHE_POOL_FILE, updated_cache)

    return final_selection
