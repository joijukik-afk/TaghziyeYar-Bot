"""Agent Search Service - API + Tavily + DDGS."""

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
        # کلید Tavily از محیط خوانده می‌شود
        self.tavily_key = os.environ.get("TAVILY_API_KEY", "")
        if self.tavily_key:
            try:
                self.tavily = TavilyClient(api_key=self.tavily_key)
            except Exception as e:
                logger.error(f"Tavily init error: {e}")
                self.tavily = None
        else:
            self.tavily = None

    async def _get_dollar_price(self) -> str:
        """گرفتن قیمت دلار از APIها و در صورت شکست، از Tavily"""
        # ۱. از API قیمت‌یاب (PriceDB)
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get("https://api.priceto.day/v1/latest/irr/usd", timeout=10)
                if res.status_code == 200:
                    price = res.json().get("price")
                    if price:
                        return f"💰 <b>قیمت دلار:</b> {int(price):,} تومان\n📊 منبع: PriceDB (لحظه‌ای)"
        except Exception:
            pass

        # ۲. از نوبیتکس (قیمت تتر)
        try:
            async with httpx.AsyncClient() as client:
                res = await client.get("https://api.nobitex.ir/v2/orderbook/USDTIRT", timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    if data.get("status") == "ok":
                        price = int(float(data.get("lastTradePrice", 0)) / 10)
                        return f"💰 <b>قیمت دلار (تتر):</b> {price:,} تومان\n📊 منبع: Nobitex"
        except Exception:
            pass

        # ۳. اگر APIها جواب ندادن، از Tavily (جستجوی وب) استفاده کن
        try:
            logger.info("Trying Tavily for dollar price...")
            context = await self._search_with_tavily("قیمت دلار آزاد امروز بازار تهران")
            if context:
                patterns = [
                    r'([۰-۹]{2,3}[,،.][۰-۹]{3})',
                    r'([0-9]{2,3}[,،.][0-9]{3})',
                    r'([0-9]{5,7})',
                    r'([۰-۹]{5,7})'
                ]
                found_prices = []
                for p in patterns:
                    found_prices.extend(re.findall(p, context))
                
                if found_prices:
                    valid_prices = []
                    for price_str in found_prices:
                        clean_str = price_str.replace(",", "").replace("،", "").replace(".", "")
                        clean_str = clean_str.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
                        try:
                            p_val = int(clean_str)
                            if 50000 < p_val < 200000: # فیلتر قیمت منطقی دلار (۵۰ تا ۲۰۰ هزار تومان)
                                valid_prices.append(p_val)
                        except:
                            pass
                    
                    if valid_prices:
                        most_common_price = Counter(valid_prices).most_common(1)[0][0]
                        return f"💰 <b>قیمت دلار:</b> {most_common_price:,} تومان\n📊 منبع: جستجوی وب زنده (Tavily)"
        except Exception as e:
            logger.warning(f"Tavily price search failed: {e}")

        # ۴. اگر هیچ‌کدام جواب نداد
        return "⚠️ متأسفانه در حال حاضر امکان دریافت قیمت لحظه‌ای وجود ندارد. لطفاً از TGJU چک کنید."

    async def _search_with_tavily(self, query: str) -> str:
        """جستجوی عمیق با Tavily"""
        if not self.tavily:
            return ""
        try:
            res = await asyncio.to_thread(
                self.tavily.search, query=query, search_depth="advanced", max_results=5
            )
            results = res.get("results", [])
            if not results:
                return ""
            
            context = "\n\n".join([f"[{r.get('title', '')}]\n{r.get('content', '')}" for r in results])
            return context
        except Exception as e:
            logger.warning(f"Tavily failed: {e}")
            return ""

    async def _search_with_ddgs(self, query: str) -> str:
        """جستجوی پشتیبان با DuckDuckGo"""
        try:
            results = await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=5)))
            if not results:
                return ""
            return "\n\n".join([f"[{r.get('title')}]\n{r.get('body')}" for r in results])
        except Exception as e:
            logger.warning(f"DDGS failed: {e}")
            return ""

    async def process(self, query: str) -> str:
        """مدیریت درخواست‌ها و انتخاب منبع مناسب"""
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
                "⚠️ <i>این کدها ممکن است منقضی شده باشند. برای کدهای لحظه‌ای، اپلیکیشن اسنپ فود را چک کنید.</i>"
            )

        # ۳. برای هر سوال دیگه‌ای (عمومی)، از Tavily استفاده کن
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
