"""سرویس جمع‌آوری و مدیریت کانفیگ‌های V2Ray از منابع گیت‌هاب"""

import re
import json
import hashlib
import logging
import random
import asyncio
from typing import List, Dict
import httpx

logger = logging.getLogger(__name__)

# --- منابع اصلی (کانفیگ‌های تست‌شده و مناسب ایران) ---
PRIMARY_SOURCES = [
    "https://raw.githubusercontent.com/liMilCo/v2r/main/best.txt",
    "https://raw.githubusercontent.com/patterniha/Free-Configs/main/configs.txt",
    "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/main/sub.txt",
    "https://raw.githubusercontent.com/barry-far/V2ray-Config/main/All_Configs_Sub.txt",
]

# --- عبارت جستجوی خودکار در گیت‌هاب (در صورت شکست منابع اصلی) ---
GITHUB_SEARCH_URL = "https://api.github.com/search/code?q=extension:txt+v2ray+config+iran&sort=updated&order=desc"

# فایل ذخیره هش کانفیگ‌های ارسال‌شده
SENT_HASHES_FILE = "sent_configs.json"

def _load_sent_hashes() -> set:
    try:
        with open(SENT_HASHES_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def _save_sent_hashes(hashes: set):
    with open(SENT_HASHES_FILE, "w") as f:
        json.dump(list(hashes), f)

async def _fetch_from_url(client: httpx.AsyncClient, url: str) -> List[str]:
    """دانلود محتوای یک URL و استخراج کانفیگ‌ها"""
    try:
        resp = await client.get(url, timeout=15.0, follow_redirects=True)
        if resp.status_code != 200:
            return []
        
        text = resp.text
        # استخراج کانفیگ‌ها با استفاده از الگوی پروتکل‌ها
        configs = re.findall(r'(?:vless|vmess|trojan|ss|ssr|hysteria2?|tuic)://[^\s]+', text, re.IGNORECASE)
        return configs
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return []

async def _search_github_for_configs(client: httpx.AsyncClient) -> List[str]:
    """جستجوی خودکار در گیت‌هاب (پشتیبان)"""
    try:
        resp = await client.get(GITHUB_SEARCH_URL, timeout=15.0)
        if resp.status_code != 200:
            return []
        data = resp.json()
        # دریافت فایل‌های خام از نتایج جستجو
        urls = [item["html_url"].replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/") for item in data.get("items", [])[:3]]
        configs = []
        for url in urls:
            configs.extend(await _fetch_from_url(client, url))
        return configs
    except Exception as e:
        logger.warning(f"GitHub search failed: {e}")
        return []

def _prioritize_for_iran(configs: List[str]) -> List[str]:
    """اولویت‌بندی کانفیگ‌ها برای اینترنت ایران (Reality و TLS)"""
    def score(c):
        # اولویت به Reality و سپس TLS
        return (0 if "security=reality" in c.lower() or "security=tls" in c.lower() else 1)
    return sorted(configs, key=score)

async def get_fresh_configs(limit: int = 10) -> List[str]:
    """تابع اصلی: دریافت کانفیگ‌های جدید و غیرتکراری"""
    sent_hashes = _load_sent_hashes()
    all_configs = []
    
    async with httpx.AsyncClient() as client:
        # ۱. تلاش برای دریافت از منابع اصلی
        tasks = [_fetch_from_url(client, url) for url in PRIMARY_SOURCES]
        results = await asyncio.gather(*tasks)
        for res_list in results:
            all_configs.extend(res_list)
        
        # ۲. اگر منابع اصلی خالی بود، جستجوی خودکار در گیت‌هاب
        if not all_configs:
            logger.info("Primary sources empty. Attempting GitHub search...")
            all_configs = await _search_github_for_configs(client)
    
    if not all_configs:
        return []
    
    # ۳. حذف تکراری‌ها بر اساس هش
    unique_configs = []
    new_hashes = set()
    for c in all_configs:
        c_hash = hashlib.md5(c.encode()).hexdigest()
        if c_hash not in sent_hashes:
            unique_configs.append(c)
            new_hashes.add(c_hash)
    
    if not unique_configs:
        return []
    
    # ۴. اولویت‌بندی برای ایران و انتخاب تصادفی از بهترین‌ها
    prioritized = _prioritize_for_iran(unique_configs)
    selected = prioritized[:limit * 2] # کمی بیشتر برای تنوع
    random.shuffle(selected)
    selected = selected[:limit]
    
    # ۵. به‌روزرسانی فایل هش‌ها
    sent_hashes.update(new_hashes)
    _save_sent_hashes(sent_hashes)
    
    return selected
