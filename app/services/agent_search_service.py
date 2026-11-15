"""Agent Search Service - Real-time APIs first, then Strict Web Search."""

import logging
import asyncio
import httpx
import re
from typing import Optional
from collections import Counter
from ddgs import DDGS
from tavily import TavilyClient

from app.config import get_settings

logger = logging.getLogger(__name__)


class AgentSearchService:
    def __init__(self):
        settings = get_settings()
        self.tavily_key = settings.tavily_api_key

        # 👈 Client مشترک برای جلوگیری از نشت اتصال
        self._http_client = httpx.AsyncClient(timeout=5.0)

        if self.tavily_key:
            try:
                self.tavily = TavilyClient(api_key=self.tavily_key)
            except Exception as e:
                logger.error(f"Tavily init error: {e}")
                self.tavily = None
        else:
            self.tavily = None

    async def close(self):
        await self._http_client.aclose()

    def _extract_dollar_price(self, text: str) -> Optional[int]:
        patterns = [
            r'([۰-۹]{3}[,،.][۰-۹]{3})',
            r'([0-9]{3}[,،.][0-9]{3})',
            r'([0-9]{6})',
            r'([۰-۹]{6})',
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
                if 100000 < p_val < 500000:
                    valid_prices.append(p_val)
            except ValueError:
                pass

        if valid_prices:
            return Counter(valid_prices).most_common(1)[0][0]
        return None

    async def _get_dollar_price(self) -> str:
        # ۱. Nobitex
        try:
            res = await self._http_client.get("https://api.nobitex.ir/v2/orderbook/USDTIRT")
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "ok":
                    price = int(float(data.get("lastTradePrice", 0)) / 10)
                    if price > 100000:
                        return f"💰 <b>قیمت دلار (تتر):</b> {price:,} تومان\n📊 منبع: Nobitex (لحظه‌ای)"
        except Exception as e:
            logger.warning(f"Nobitex failed: {e}")

        # ۲. Wallex
        try:
            res = await self._http_client.get("https://api.wallex.ir/v1/markets")
            if res.status_code == 200:
                symbols = res.json().get("result", {}).get("symbols", {})
                if "USDTIRT" in symbols:
                    price = int(float(symbols["USDTIRT"]["stats"]["lastPrice"]))
                    if price > 100000:
                        return f"💰 <b>قیمت دلار (تتر):</b> {price:,} تومان\n📊 منبع: Wallex (لحظه‌ای)"
        except Exception as e:
            logger.warning(f"Wallex failed: {e}")

        # ۳. Tavily
        if self.tavily:
            try:
                res = await asyncio.to_thread(
                    self.tavily.search,
                    query="قیمت دلار آزاد امروز بازار تهران",
                    search_depth="advanced",
                    max_results=5,
                    include_domains=["tgju.org", "bonbast.com", "alanchand.com", "tejaratnews.com"],
                )
                results = res.get("results", [])
                if results:
                    context = "\n\n".join([f"[{r.get('title', '')}]\n{r.get('content', '')}" for r in results])
                    price = self._extract_dollar_price(context)
                    if price:
                        return f"💰 <b>قیمت دلار آزاد:</b> {price:,} تومان\n📊 منبع: جستجوی وب زنده"
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
            return "\n\n".join([f"[{r.get('title', 'No Title')}]\n{r.get('body', '')}" for r in results])
        except Exception as e:
            logger.warning(f"DDGS failed: {e}")
            return ""

    async def _get_discount_codes(self, query: str) -> str:
        context = await self._search_with_tavily(query)
        if not context:
            context = await self._search_with_ddgs(query)

        if context:
            codes = re.findall(r'\b[A-Z][A-Z0-9\-]{3,15}\b', context)
            blacklist = {"HTTP", "HTTPS", "HTML", "PHP", "API", "OFFCH", "MOPON", "THE", "AND", "FOR", "WITH"}
            codes = list(set([c for c in codes if c not in blacklist]))

            if codes:
                result = "🎟️ <b>کدهای تخفیف پیدا شده:</b>\n\n"
                for c in codes[:5]:
                    result += f"• <code>{c}</code>\n"
                result += "\n📌 این کدها از سایت‌های تخفیف‌یاب معتبر استخراج شده‌اند."
                return result

        return ""

    async def process(self, query: str) -> str:
        q = query.lower()

        if any(k in q for k in ["قیمت دلار", "دلار چنده", "تتر", "نرخ دلار"]):
            return await self._get_dollar_price()

        if "اسنپ فود" in q and ("کد" in q or "تخفیف" in q):
            result = await self._get_discount_codes("کد تخفیف اسنپ فود offch.com mopon.ir")
            if result:
                return result

            return (
                "🎟️ <b>کدهای تخفیف فعال اسنپ فود:</b>\n\n"
                "• <code>Snapp-Restaurant</code> (۱۰۰ هزار تومان)\n"
                "• <code>Snapp-Confectionery</code> (۳۵ هزار تومان)\n"
                "• <code>Snapp-Ajil</code> (۵۰ هزار تومان)\n"
                "• <code>Snapp-Juice</code> (۳۵ هزار تومان)\n"
                "• <code>Snapp-Cafe</code> (۴۰ هزار تومان)\n\n"
                "⚠️ <i>این کدها ممکن است منقضی شده باشند.</i>"
            )

        context = await self._search_with_tavily(query)
        if not context:
            context = await self._search_with_ddgs(query)

        return context


_agent_search_service: Optional[AgentSearchService] = None


def get_agent_search_service() -> AgentSearchService:
    global _agent_search_service
    if _agent_search_service is None:
        _agent_search_service = AgentSearchService()
    return _agent_search_service
