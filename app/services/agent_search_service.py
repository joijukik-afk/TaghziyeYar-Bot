"""Agent Search Service - Real-time APIs first, then Strict Web Search."""

import logging
import asyncio
import httpx
import re
import os
from typing import Optional
from collections import Counter
from ddgs import DDGS
from tavily import TavilyClient

logger = logging.getLogger(__name__)

class AgentSearchService:
    def __init__(self):
        self.tavily_key = os.environ.get("TAVILY_API_KEY", "")
        if self.tavily_key:
            try:
                self.tavily = TavilyClient(api_key=self.tavily_key)
            except Exception as e:
                logger.error(f"Tavily init error: {e}")
                self.tavily = None
        else:
            self.tavily = None

    def _extract_dollar_price(self, text: str) -> Optional[int]:
        """استخراج قیمت دلار آزاد با فیلتر دقیق"""
        patterns = [
            r'([۰-۹]{3}[,،.][۰-۹]{3})',  # ۲۷۱,۳۶۰
            r'([0-9]{3}[,،.][0-9]{3})',  # 271,360
            r'([0-9]{6})',               # 271360
            r'([۰-۹]{6})'                # ۲۷۱۳۶۰
        ]
        found_prices = []
        for p in patterns:
            found_prices.extend(re.findall(p, text))
        
        valid_prices = []
        for price_str in found_prices:
            clean_str = price_str.replace(",", "").replace("،", "").replace(".", "")
            clean_str = clean_str.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            try:
                p_val = int(clean_str)
                # فیلتر قیمت منطقی دلار آزاد (۲۵۰ تا ۳۰۰ هزار تومان)
                if 250000 < p_val < 300000:
                    valid_prices.append(p_val)
            except:
                pass
        
        if valid_prices:
            return Counter(valid_prices).most_common(1)[0][0]
        return None

    async def _get_dollar_price(self) -> str:
        """گرفتن قیمت دلار آزاد از APIها و در صورت شکست، از Tavily"""
        
        # ۱. از API نوبیتکس (دقیق‌ترین)
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get("https://api.nobitex.ir/v2/orderbook/USDTIRT", timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("status") == "ok":
                        price = int(float(data.get("lastTradePrice", 0)) / 10)
                        if price > 200000:
                            return f"💰 <b>قیمت دلار (تتر):</b> {price:,} تومان\n📊 منبع: Nobitex (لحظه‌ای)"
        except Exception:
            pass

        # ۲. از API والکس
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get("https://api.wallex.ir/v1/markets", timeout=5)
                if res.status_code == 200:
                    symbols = res.json().get("result", {}).get("symbols", {})
                    if "USDTIRT" in symbols:
                        price = int(float(symbols["USDTIRT"]["stats"]["lastPrice"]))
                        if price > 200000:
                            return f"💰 <b>قیمت دلار (تتر):</b> {price:,} تومان\n📊 منبع: Wallex (لحظه‌ای)"
        except Exception:
            pass

        # ۳. از Tavily (فقط سایت‌های معتبر و لحظه‌ای)
        try:
            logger.info("Trying Tavily for dollar price...")
            # جستجو فقط در سایت‌های معتبر
            res = await asyncio.to_thread(
                self.tavily.search, 
                query="قیمت دلار آزاد امروز بازار تهران", 
                search_depth="advanced", 
                max_results=5,
                include_domains=["tgju.org", "bonbast.com", "alanchand.com", "tejaratnews.com"]
            )
            results = res.get("results", [])
            if results:
                context = "\n\n".join([f"[{r.get('title', '')}]\n{r.get('content', '')}" for r in results])
                price = self._extract_dollar_price(context)
                if price:
                    return f"💰 <b>قیمت دلار آزاد:</b> {price:,} تومان\n📊 منبع: جستجوی وب زنده (Tavily)"
        except Exception as e:
            logger.warning(f"Tavily price search failed: {e}")

        return "⚠️ متأسفانه در حال حاضر امکان دریافت قیمت لحظه‌ای وجود ندارد. لطفاً از TGJU چک کنید."

    async def _search_with_tavily(self, query: str) -> str:
        if not self.tavily:
            return ""
        try:
            res = await asyncio.to_thread(
                self.tavily.search, query=query, search_depth="advanced", max_results=5
            )
            results = res.get("results", [])
            if not results:
                return ""
            return "\n\n".join([f"[{r.get('title', '')}]\n{r.get('content', '')}" for r in results])
        except Exception as e:
            logger.warning(f"Tavily failed: {e}")
            return ""

    async def _search_with_ddgs(self, query: str) -> str:
        try:
            results = await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=5)))
            if not results:
                return ""
            return "\n\n".join([f"[{r.get('title')}]\n{r.get('body')}" for r in results])
        except Exception as e:
            logger.warning(f"DDGS failed: {e}")
            return ""

    async def process(self, query: str) -> str:
        q = query.lower()
        
        # ۱. اگر کاربر قیمت دلار خواست
        if any(k in q for k in ["قیمت دلار", "دلار چنده", "تتر", "نرخ دلار"]):
            return await self._get_dollar_price()

        # ۲. اگر کاربر کد تخفیف اسنپ فود خواست
        if "اسنپ فود" in q and ("کد" in q or "تخفیف" in q):
            context = await self._search_with_tavily("کد تخفیف اسنپ فود offch.com mopon.ir")
            if not context:
                context = await self._search_with_ddgs("کد تخفیف اسنپ فود offch.com mopon.ir")
            
            if context:
                codes = re.findall(r'\b[A-Z][A-Z0-9\-]{3,15}\b', context)
                codes = list(set([c for c in codes if c not in ["HTTP", "HTTPS", "HTML", "PHP", "API", "OFFCH", "MOPON"]]))
                
                if codes:
                    result = "🎟️ <b>کدهای تخفیف اسنپ فود پیدا شده:</b>\n\n"
                    for c in codes[:5]:
                        result += f"• <code>{c}</code>\n"
                    result += "\n📌 این کدها از سایت‌های تخفیف‌یاب معتبر استخراج شده‌اند."
                    return result
            
            return (
                "🎟️ <b>کدهای تخفیف فعال اسنپ فود:</b>\n\n"
                "• <code>Snapp-Restaurant</code> (۱۰۰ هزار تومان - سفارش اول رستوران)\n"
                "• <code>Snapp-Confectionery</code> (۳۵ هزار تومان - سفارش اول قنادی)\n"
                "• <code>Snapp-Ajil</code> (۵۰ هزار تومان - سفارش اول آجیل)\n"
                "• <code>Snapp-Juice</code> (۳۵ هزار تومان - آبمیوه و بستنی)\n"
                "• <code>Snapp-Cafe</code> (۴۰ هزار تومان - کافه)\n\n"
                "⚠️ <i>این کدها ممکن است منقضی شده باشند.</i>"
            )

        # ۳. برای هر سوال دیگه‌ای (عمومی)
        context = await self._search_with_tavily(query)
        if not context:
            context = await self._search_with_ddgs(query)
        
        return context

_agent_search_service = None
def get_agent_search_service() -> AgentSearchService:
    global _agent_search_service
    if _agent_search_service is None:
        _agent_search_service = AgentSearchService()
    return _agent_search_service
