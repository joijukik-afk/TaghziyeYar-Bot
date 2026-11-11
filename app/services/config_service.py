"""موتور قدرتمند دریافت و تست کانفیگ V2Ray (بدون نیاز به کتابخانه اضافی)"""

import asyncio
import hashlib
import json
import logging
import random
import re
import socket
import urllib.parse
from typing import List, Optional
import httpx

logger = logging.getLogger(__name__)

# --- منابع برتر و تایید‌شده (به‌روزرسانی مداوم) ---
TOP_SOURCES = [
    "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/verified/top100.txt",
    "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/fast/configs.txt",
    "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt",
    "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/mix",
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
        logger.error(f"خطا در ذخیره {path}: {e}")

async def _fetch_source(client: httpx.AsyncClient, url: str) -> List[str]:
    try:
        resp = await client.get(url, timeout=12.0, follow_redirects=True)
        if resp.status_code != 200:
            return []
        return re.findall(r'(?:vless|vmess|trojan|ss|ssr|hysteria2?|tuic)://[^\s]+', resp.text, re.IGNORECASE)
    except Exception as e:
        logger.warning(f"خطا در دریافت ({url}): {e}")
        return []

def _prioritize_for_iran(configs: List[str]) -> List[str]:
    def score(c):
        cl = c.lower()
        if "security=reality" in cl: return 0 
        if "hysteria2" in cl or "hy2" in cl: return 1 
        if "security=tls" in cl or "port=443" in cl: return 2 
        return 3
    return sorted(configs, key=score)

def _test_tcp_alive(host: str, port: int) -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.5)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
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

async def _filter_alive_configs(configs: List[str]) -> List[str]:
    alive = []
    sem = asyncio.Semaphore(40)
    
    async def check(c):
        hp = _parse_host_port(c)
        if not hp: return c
        host, port = hp
        async with sem:
            is_alive = await asyncio.to_thread(_test_tcp_alive, host, port)
            if is_alive:
                return c
        return None

    results = await asyncio.gather(*(check(c) for c in configs))
    for r in results:
        if r: alive.append(r)
    return alive

async def get_fresh_configs(limit: int = 10) -> List[str]:
    sent_hashes = set(_load_json(SENT_HASHES_FILE))
    cache_good = _load_json(CACHE_POOL_FILE)
    
    if len(sent_hashes) > 10000:
        sent_hashes.clear()
        _save_json(SENT_HASHES_FILE, [])

    raw_configs = []
    async with httpx.AsyncClient() as client:
        tasks = [_fetch_source(client, url) for url in TOP_SOURCES]
        results = await asyncio.gather(*tasks)
        for res in results:
            raw_configs.extend(res)

    unique_new = []
    new_hashes = set()
    seen_now = set()
    for c in raw_configs:
        h = hashlib.md5(c.encode()).hexdigest()
        if h not in sent_hashes and h not in seen_now:
            unique_new.append(c)
            new_hashes.add(h)
            seen_now.add(h)

    prioritized = _prioritize_for_iran(unique_new)
    to_test = prioritized[:40]
    
    alive_configs = await _filter_alive_configs(to_test)
    
    final_selection = alive_configs[:limit]
    
    if len(final_selection) < limit:
        for c in prioritized:
            if len(final_selection) >= limit: break
            if c not in final_selection:
                final_selection.append(c)

    if len(final_selection) < limit and cache_good:
        random.shuffle(cache_good)
        for c in cache_good:
            if len(final_selection) >= limit: break
            if c not in final_selection:
                final_selection.append(c)

    if final_selection:
        sent_hashes.update(new_hashes)
        _save_json(SENT_HASHES_FILE, list(sent_hashes))
        updated_cache = list(set(final_selection + cache_good))[:100]
        _save_json(CACHE_POOL_FILE, updated_cache)

    return final_selection
