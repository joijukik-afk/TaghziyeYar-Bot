"""موتور دریافت و تست پروکسی MTProto با هشدار امنیتی"""

import asyncio
import logging
import time
import html
from typing import List, Dict
import httpx
import urllib.parse
from telegram import Update
from telegram.ext import ContextTypes
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

PROXY_SOURCES = [
    "https://raw.githubusercontent.com/Grim1313/mtproto-for-telegram/master/all_proxies.txt",
    "https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt",
]

_proxy_cache: dict = {"data": None, "timestamp": 0}
_CACHE_TTL = 1800
_PROXY_COOLDOWN = 30
_last_proxy_time: dict[int, float] = {}

_http_client = httpx.AsyncClient(
    timeout=10.0, follow_redirects=True,
    headers={"User-Agent": "Mozilla/5.0 TaghziyeYar/1.0"},
)

async def _fetch_source(url: str) -> List[str]:
    try:
        resp = await _http_client.get(url)
        resp.raise_for_status()
        return [line.strip() for line in resp.text.split("\n") if line.strip() and "t.me/proxy" in line]
    except Exception as e:
        logger.warning(f"Fetch error for {url}: {e}", exc_info=True)
        return []

async def _test_proxy_alive(server: str, port: int, timeout: float = 5.0) -> bool:
    writer = None
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(server, port), timeout=timeout)
        return True
    except Exception:
        return False
    finally:
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception: pass

async def _get_proxies_cached() -> List[Dict]:
    now = time.time()
    if _proxy_cache["data"] is not None and (now - _proxy_cache["timestamp"]) < _CACHE_TTL:
        return _proxy_cache["data"]

    results = await asyncio.gather(*[_fetch_source(url) for url in PROXY_SOURCES], return_exceptions=True)
    all_links = []
    for res in results:
        if isinstance(res, list): all_links.extend(res)

    if not all_links: return []

    valid_proxies = []
    seen = set()
    for link in all_links:
        if link.startswith("tg://proxy?"): link = link.replace("tg://proxy?", "https://t.me/proxy?")
        if link in seen or "t.me/proxy?" not in link: continue
        seen.add(link)
        try:
            parsed = urllib.parse.urlparse(link)
            query = urllib.parse.parse_qs(parsed.query)
            server = query.get("server", [""])[0]
            port_str = query.get("port", ["0"])[0]
            if not server or not port_str.isdigit(): continue
            port = int(port_str)
            if not (1 <= port <= 65535): continue
            valid_proxies.append({"link": link, "server": server, "port": port})
        except Exception: continue

    proxies_to_test = valid_proxies[:30]
    test_results = await asyncio.gather(*[_test_proxy_alive(p["server"], p["port"]) for p in proxies_to_test])
    alive_proxies = [p for p, alive in zip(proxies_to_test, test_results) if alive]

    _proxy_cache["data"] = alive_proxies
    _proxy_cache["timestamp"] = now
    return alive_proxies

async def get_best_proxies(limit: int = 10) -> List[Dict]:
    try:
        proxies = await _get_proxies_cached()
        return [{"proxy": p["link"]} for p in proxies[:limit]]
    except Exception as e:
        logger.error(f"get_best_proxies failed: {e}", exc_info=True)
        return []

SECURITY_WARNING = (
    "⚠️ <b>هشدار امنیتی مهم:</b>\n\n"
    "این پروکسی‌ها از منابع عمومی جمع‌آوری شده‌اند و <b>هیچ تضمینی برای امنیت آن‌ها وجود ندارد.</b>\n"
    "🔴 ممکن است ترافیک شما استراق سمع شود (MITM).\n"
    "✅ توصیه: استفاده از پروکسی رسمی تلگرام یا سرور شخصی.\n"
    "🔒 <i>استفاده با مسئولیت خود شماست.</i>"
)

async def cmd_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user: return
    user_id = update.effective_user.id

    now = time.time()
    if user_id in _last_proxy_time and now - _last_proxy_time[user_id] < _PROXY_COOLDOWN:
        return await update.message.reply_text(with_signature(f"⏳ لطفاً {_PROXY_COOLDOWN} ثانیه صبر کنید."), parse_mode="HTML")
    _last_proxy_time[user_id] = now

    status = await update.message.reply_text("🔍 در حال جمع‌آوری و تست پروکسی‌ها...")
    try: await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception: pass

    try:
        proxies = await get_best_proxies(limit=10)
        if not proxies:
            return await status.edit_text(with_signature("❌ پروکسی زنده‌ای پیدا نشد. بعداً تلاش کنید."), parse_mode="HTML")

        lines = [SECURITY_WARNING, "", "🔗 <b>پروکسی‌های پیشنهادی:</b>\n"]
        for i, p in enumerate(proxies, 1):
            safe_link = html.escape(p["proxy"], quote=True)
            lines.append(f"{i}. <a href='{safe_link}'>پروکسی {i}</a>")

        final_text = with_signature("\n".join(lines))
        try:
            await status.edit_text(final_text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            import re
            await status.edit_text(re.sub(r"<[^>]+>", "", final_text), disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"cmd_proxy error: {e}", exc_info=True)
        await status.edit_text("❌ خطا در دریافت پروکسی.")

# 👈 تابعی که باعث خطا شده بود (اضافه شد)
async def handle_proxy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """هندلر خالی برای دکمه‌های شیشه‌ای پروکسی جهت جلوگیری از خطای AttributeError"""
    query = update.callback_query
    if query:
        await query.answer("این بخش فعلاً غیرفعال است.", show_alert=True)
