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

# --- لایه ۱: منابع طلایی (بسیار قوی و آپدیت روزانه) ---
GOLD_SOURCES = [
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/mix",
    "https://raw.githubusercontent.com/Soroushmirzaei/telegram-configs-collector/main/protocols/reality",
    "https://raw.githubusercontent.com/mahdibland/ShadowsocksAggregator/master/Eternity.txt",
]

# --- لایه ۲: منابع نقره‌ای (جایگزین) ---
SILVER_SOURCES = [
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/liMilCo/v2r/main/best.txt",
    "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/sub.txt",
]

SENT_HASHES_FILE = "sent_configs.json"
CACHE_GOOD_CONFIGS_FILE = "cache_good_configs.json"
MAX_HASH_MEMORY = 5000 # اگر حافظه از این بیشتر شد، ریست میشه

def _load_json(filepath: str) -> list:
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception:
        return []

def _save_json(filepath: str, data: list):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.error(f"Could not save {filepath}: {e}")

async def _fetch_url(client: httpx.AsyncClient, url: str) -> List[str]:
    """دانلود و استخراج کانفیگ‌ها از یک لینک"""
    try:
        resp = await client.get(url, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            return []
        # استخراج تمام پروتکل‌های ممکن
        return re.findall(r'(?:vless|vmess|trojan|ss|ssr|hysteria2?|tuic)://[^\s]+', resp.text, ignore_ignorecase=True)
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return []

async def _test_tcp(host: str, port: int) -> bool:
    """تست سریع TCP (حداکثر ۲ ثانیه)"""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=2.0)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False

def _parse_host_port(config: str) -> Optional[tuple]:
    """استخراج هاست و پورت از لینک"""
    try:
        # استثنا برای vmess (چون فرمت Base64 داره)
        if config.startswith("vmess://"):
            return None
            
        parsed = urllib.parse.urlparse(config)
        if parsed.hostname and parsed.port:
            return parsed.hostname, parsed.port
    except Exception:
        pass
    return None

async def _filter_alive(configs: List[str]) -> List[str]:
    """تست همزمان و فیلتر کردن کانفیگ‌های زنده"""
    alive = []
    sem = asyncio.Semaphore(40) # 40 تست همزمان
    
    async def check(c):
        hp = _parse_host_port(c)
        if not hp: return c # vmess و موارد خاص رو نگه دار
        host, port = hp
        async with sem:
            if await _test_tcp(host, port):
                return c
        return None

    results = await asyncio.gather(*(check(c) for c in configs))
    for r in results:
        if r: alive.append(r)
    return alive

def _prioritize(configs: List[str]) -> List[str]:
    """اولویت‌بندی: Reality اول، TLS دوم، بقیه سوم"""
    def score(c):
        cl = c.lower()
        if "security=reality" in cl: return 0
        if "security=tls" in cl or "port=443" in cl: return 1
        return 2
    return sorted(configs, key=score)

async def get_fresh_configs(limit: int = 10) -> List[str]:
    """تابع اصلی: جستجو در لایه‌ها، تست، و انتخاب"""
    sent_hashes = set(_load_json(SENT_HASHES_FILE))
    cache_good = _load_json(CACHE_GOOD_CONFIGS_FILE)
    
    # اگر حافظه پر شده بود، ریست کن تا دوباره از اول بفرسته
    if len(sent_hashes) > MAX_HASH_MEMORY:
        logger.info("Resetting sent hashes memory...")
        sent_hashes.clear()
        _save_json(SENT_HASHES_FILE, [])

    raw_configs = []
    
    async with httpx.AsyncClient() as client:
        # ۱. تلاش در لایه طلایی
        tasks = [_fetch_url(client, url) for url in GOLD_SOURCES]
        gold_results = await asyncio.gather(*tasks)
        for res in gold_results:
            raw_configs.extend(res)
            
        # ۲. اگر خیلی کم بود، لایه نقره‌ای رو هم اضافه کن
        if len(raw_configs) < 50:
            logger.info("Gold layer yielded few results. Fetching silver layer...")
            tasks_silver = [_fetch_url(client, url) for url in SILVER_SOURCES]
            silver_results = await asyncio.gather(*tasks_silver)
            for res in silver_results:
                raw_configs.extend(res)

    # ۳. حذف تکراری‌ها
    unique_new = []
    new_hashes = set()
    seen_now = set()
    
    for c in raw_configs:
        h = hashlib.md5(c.encode()).hexdigest()
        if h not in sent_hashes and h not in seen_now:
            unique_new.append(c)
            new_hashes.add(h)
            seen_now.add(h)

    # ۴. تست زنده بودن
    alive_configs = await _filter_alive(unique_new)
    
    # ۵. اولویت‌بندی
    prioritized = _prioritize(alive_configs)
    
    final_selection = prioritized[:limit]
    
    # ۶. **سیستم نجات‌بخش:** اگر جدید نبود، از Cache بده
    if len(final_selection) < limit and cache_good:
        logger.info("Using backup cache to fill the gap...")
        random.shuffle(cache_good)
        for c in cache_good:
            if len(final_selection) >= limit: break
            if c not in final_selection:
                final_selection.append(c)

    # ۷. اگر Cache هم خالی بود (بار اول)، دوباره از کانفیگ‌های خام (بدون تست) بده
    if len(final_selection) < limit and raw_configs:
        logger.info("Using raw configs as last resort...")
        random.shuffle(raw_configs)
        for c in raw_configs:
            if len(final_selection) >= limit: break
            if c not in final_selection:
                final_selection.append(c)

    # ۸. ذخیره در حافظه
    if final_selection:
        sent_hashes.update(new_hashes)
        _save_json(SENT_HASHES_FILE, list(sent_hashes))
        
        # آپدیت Cache (حداکثر 100 تا نگه داریم)
        updated_cache = list(set(final_selection + cache_good))[:100]
        _save_json(CACHE_GOOD_CONFIGS_FILE, updated_cache)

    return final_selection
