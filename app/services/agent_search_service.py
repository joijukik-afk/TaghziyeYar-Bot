"""Agent Search Service - Multi-Source (API + Scraping + DDGS)."""

import logging
import asyncio
import httpx
import re
from typing import Optional, List, Dict
from ddgs import DDGS
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

class AgentSearchService:
    def __init__(self):
        self.ai_service = get_ai_service()

    async def _get_price_from_api(self) -> Optional[str]:
        """گرفتن قیمت دلار از APIهای رایگان و معتبر"""
        # منبع ۱: api.priceto.day (بدون کلید، هر ۳۰ دقیقه آپدیت)
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get("https://api.priceto.day/v1/latest/irr/usd")
                if resp.status_code == 200:
                    data = resp.json()
                    price = data.get("price")
                    if price:
                        return f"💰 <b>قیمت دلار:</b> {int(price):,} تومان\n📊 منبع: PriceDB (لحظه‌ای)"
        except Exception as e:
            logger.warning(f"PriceDB API failed: {e}")

        # منبع ۲: tgju-mcp (اگه در دسترس باشه)
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get("http://localhost:8000/tj_market_summary")
                if resp.status_code == 200:
                    data = resp.json()
                    # ساختار فرضی: {"dollar": {"value": 270000}}
                    dollar = data.get("dollar", {}).get("value")
                    if dollar:
                        return f"💰 <b>قیمت دلار:</b> {int(dollar):,} تومان\n📊 منبع: TGJU (لحظه‌ای)"
        except Exception:
            pass

        return None

    async def _get_discount_codes(self, query: str) -> Optional[str]:
        """گرفتن کد تخفیف از سایت‌های تخصصی (Mopon, Offch)"""
        # این یک نمونه است. در عمل باید اسکرپینگ انجام بشه.
        # برای سادگی، فعلاً از DDGS استفاده می‌کنیم ولی با کوئری دقیق‌تر
        return None

    def _extract_prices(self, text: str) -> List[str]:
        """استخراج اعداد قیمت (فارسی و انگلیسی)"""
        patterns = [
            r'([۰-۹]{2,3}[,،.][۰-۹]{3})',
            r'([0-9]{2,3}[,،.][0-9]{3})',
            r'([0-9]{5,7})',
            r'([۰-۹]{5,7})'
        ]
        found = []
        for p in patterns:
            found.extend(re.findall(p, text))
        return list(dict.fromkeys(found))[:10]

    def _extract_codes(self, text: str) -> List[str]:
        """استخراج کدهای تخفیف"""
        pattern = r'\b[A-Z][A-Z0-9]{3,11}\b'
        codes = re.findall(pattern, text)
        blacklist = ["HTTP", "HTTPS", "HTML", "PHP", "TRUE", "FALSE", "NULL"]
        return list(dict.fromkeys([c for c in codes if c not in blacklist]))[:10]

    async def search(self, query: str) -> Dict[str, any]:
        """جستجوی جامع: اول API، بعد DDGS"""
        logger.info(f"🔍 Searching for: {query}")
        
        # ۱. اگه درباره قیمت دلار/طلاست، اول از API بگیر
        if any(k in query.lower() for k in ["قیمت دلار", "دلار چنده", "نرخ دلار", "تتر", "طلا", "سکه"]):
            api_price = await self._get_price_from_api()
            if api_price:
                return {
                    "snippets": "",
                    "prices": [],
                    "codes": [],
                    "urls": [],
                    "api_result": api_price
                }

        # ۲. در غیر این صورت، از DDGS استفاده کن
        queries = [query]
        if "کد" in query or "تخفیف" in query:
            queries.append("کد تخفیف اسنپ فود امروز")
            queries.append("کد تخفیف دیجی کالا جدید")

        all_snippets = []
        all_urls = []
        
        for q in queries:
            try:
                results = await asyncio.to_thread(lambda q=q: list(DDGS().text(q, max_results=5)))
                for r in results:
                    body = r.get("body", "")
                    title = r.get("title", "")
                    href = r.get("href", "")
                    if body:
                        all_snippets.append(f"[{title}] {body}")
                        all_urls.append(href)
            except Exception as e:
                logger.warning(f"DDGS failed for '{q}': {e}")

        combined_text = "\n".join(all_snippets)
        
        return {
            "snippets": combined_text,
            "prices": self._extract_prices(combined_text),
            "codes": self._extract_codes(combined_text),
            "urls": all_urls[:5],
            "api_result": None
        }

_agent_search_service = None
def get_agent_search_service() -> AgentSearchService:
    global _agent_search_service
    if _agent_search_service is None:
        _agent_search_service = AgentSearchService()
    return _agent_search_service
