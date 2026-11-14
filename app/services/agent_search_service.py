"""Agent Search Service - API + Tavily + DDGS."""

import logging
import asyncio
import httpx
import re
import os
from typing import Optional
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
        """گرفتن قیمت دلار از APIهای معتبر (بدون فیلترشکن)"""
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

        return "⚠️ متأسفانه در حال حاضر امکان دریافت قیمت دلار وجود ندارد. لطفاً از TGJU چک کنید."

    async def _search_with_tavily(self, query: str) -> str:
        """جستجوی عمیق با Tavily"""
        if not self.tavily:
            return ""
        try:
            # جستجوی پیشرفته برای گرفتن متن کامل سایت‌ها
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
            # اول با Tavily در سایت‌های تخصصی تخفیف‌یاب می‌گردیم
            context = await self._search_with_tavily("کد تخفیف اسنپ فود offch.com mopon.ir")
            if not context:
                context = await self._search_with_ddgs("کد تخفیف اسنپ فود offch.com mopon.ir")
            
            if context:
                # استخراج کدهای شبیه به کد تخفیف (حروف بزرگ و اعداد)
                codes = re.findall(r'\b[A-Z][A-Z0-9\-]{3,15}\b', context)
                codes = list(set([c for c in codes if c not in ["HTTP", "HTTPS", "HTML", "PHP", "API", "OFFCH", "MOPON"]]))
                
                if codes:
                    result = "🎟️ <b>کدهای تخفیف اسنپ فود پیدا شده:</b>\n\n"
                    for c in codes[:5]:
                        result += f"• <code>{c}</code>\n"
                    result += "\n📌 این کدها از سایت‌های تخفیف‌یاب معتبر استخراج شده‌اند. قبل از استفاده، اعتبار آن‌ها را چک کنید."
                    return result
            
            # اگر Tavily کدی پیدا نکرد، لیست پیش‌فرض کدهای فعال را نشان می‌دهیم
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
