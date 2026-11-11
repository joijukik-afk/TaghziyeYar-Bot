"""موتور قدرتمند دریافت کانفیگ V2Ray (با محدودیت تست برای جلوگیری از تایم‌اوت)"""

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

# منابع بسیار قوی
TOP_SOURCES = [
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/DukeMehdi/FreeList-V2ray-Configs/refs/heads/main/Configs/All-DukeMehdi-Configs.txt",
    "https://raw.githubusercontent.com/liMilCo/v2r/main/best.txt",
    "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/sub.txt",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/mix",
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
        resp = await client.get(url, timeout=10.0, follow_redirects=True)
        if resp.status_code != 200:
            return []
        return re.findall(r'(?:vless|vmess|trojan|ss|ssr|hysteria2?|tuic)://[^\s]+', resp.text, re.IGNORECASE)
    except Exception as e:
        logger.warning(f"Fetch warning ({url}): {e}")
        return []

async def _test_tcp_alive(host: str, port: int) -> bool:
    """تست سریع TCP با تایم‌اوت سختگیرانه (۱.۵ ثانیه)"""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.5)
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

def _prioritize(configs: List[str]) -> List[str]:
    def score(c):
        cl = c.lower()
        if "security=reality" in cl: return 0
        if "security=tls" in cl or "port=443" in cl: return 1
        return 2
    return sorted(configs, key=score)

async def get_fresh_configs(limit: int = 15) -> List[str]:
    sent_hashes = set(_load_json(SENT_HASHES_FILE))
    cache_good = _load_json(CACHE_POOL_FILE)
    
    if len(sent_hashes) > 10000:
        sent_hashes.clear()
        _save_json(SENT_HASHES_FILE, [])

    raw_configs = []
    
    # ۱. دانلود سریع از منابع
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_source(client, url) for url in TOP_SOURCES]
        results = await asyncio.gather(*tasks)
        for res in results:
            raw_configs.extend(res)

    # ۲. حذف تکراری‌ها
    unique_new = []
    new_hashes = set()
    seen_now = set()
    
    for c in raw_configs:
        h = hashlib.md5(c.encode()).hexdigest()
        if h not in sent_hashes and h not in seen_now:
            unique_new.append(c)
            new_hashes.add(h)
            seen_now.add(h)

    # 🚀 ۳. **محدودیت تست (مهم‌ترین بخش):** فقط ۴۰ کانفیگ رندوم رو تست میکنیم تا سرعت بالا باشه
    if len(unique_new) > 40:
        unique_new = random.sample(unique_new, 40)

    # ۴. تست همزمان
    alive_configs = []
    sem = asyncio.Semaphore(20)
    
    async def check(c):
        hp = _parse_host_port(c)
        if not hp: return c
        host, port = hp
        async with sem:
            if await _test_tcp_alive(host, port):
                return c
        return None

    results = await asyncio.gather(*(check(c) for c in unique_new))
    for r in results:
        if r: alive_configs.append(r)

    # ۵. اولویت‌بندی و انتخاب
    prioritized = _prioritize(alive_configs)
    final_selection = prioritized[:limit]
    
    # ۶. اگر خالی بود، از کانفیگ‌های تست‌نشده (همون ۴۰ تای رندوم) بده
    if len(final_selection) < limit:
        for c in unique_new:
            if len(final_selection) >= limit: break
            if c not in final_selection:
                final_selection.append(c)

    # ۷. سیستم نجات نهایی (Cache)
    if len(final_selection) < limit and cache_good:
        random.shuffle(cache_good)
        for c in cache_good:
            if len(final_selection) >= limit: break
            if c not in final_selection:
                final_selection.append(c)

    # ذخیره در حافظه
    if final_selection:
        sent_hashes.update(new_hashes)
        _save_json(SENT_HASHES_FILE, list(sent_hashes))
        updated_cache = list(set(final_selection + cache_good))[:100]
        _save_json(CACHE_POOL_FILE, updated_cache)

    return final_selection
