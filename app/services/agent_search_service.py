import asyncio
import logging
import re
import httpx
from curl_cffi import requests as curl_requests
from bs4 import BeautifulSoup
from ddgs import DDGS

logger = logging.getLogger(__name__)

class AgentSearchService:
    def __init__(self):
        pass

    async def _fetch(self, url: str) -> str:
        try:
            res = await asyncio.to_thread(
                curl_requests.get, url, impersonate="chrome120", timeout=10
            )
            if res.status_code == 200:
                return res.text
        except Exception as e:
            logger.warning(f"Fetch error {url}: {e}")
        return ""

    async def _get_dollar_price(self) -> str:
        # ۱. از API رسمی TGJU
        try:
            res = await asyncio.to_thread(
                curl_requests.get, "https://api.tgju.org/v1/market/indicator/summary-table-data", impersonate="chrome120", timeout=10
            )
            if res.status_code == 200:
                data = res.json()
                for item in data.get("data", []):
                    if item.get("symbol") == "price_dollar_rl":
                        price = item.get("value")
                        if price:
                            return f"💰 <b>قیمت دلار:</b> {int(price):,} تومان\n📊 منبع: TGJU (لحظه‌ای)"
        except Exception as e:
            logger.warning(f"TGJU API failed: {e}")

        # ۲. اسکرپینگ سایت Bonbast
        html = await self._fetch("https://www.bonbast.com/")
        if html:
            try:
                soup = BeautifulSoup(html, 'html.parser')
                usd_row = soup.find('td', string=re.compile(r'US Dollar', re.I))
                if usd_row:
                    sell = usd_row.find_next_sibling('td').find_next_sibling('td')
                    price = int(re.sub(r'\D', '', sell.text))
                    return f"💰 <b>قیمت دلار:</b> {price:,} تومان\n📊 منبع: Bonbast.com"
            except Exception as e:
                logger.warning(f"Bonbast parse error: {e}")

        # ۳. از API نوبیتکس (تتر)
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

        return "⚠️ متأسفانه در حال حاضر امکان دریافت قیمت دلار وجود ندارد. لطفاً از سایت‌های معتبر (TGJU, Bonbast) چک کنید."

    async def _get_snapp_discounts(self) -> str:
        urls = [
            "https://www.offch.com/shops/snappfood",
            "https://www.mopon.ir/%DA%A9%D8%AF-%D8%AA%D8%AE%D9%81%DB%8C%D9%81-%D8%A7%D8%B3%D9%86%D9%BE-%D9%81%D9%88%D8%AF/%D8%B3%D9%81%D8%A7%D8%B1%D8%B4-%D8%BA%D8%B0%D8%A7/%DA%A9%D9%88%D9%BE%D9%86"
        ]
        text = ""
        for url in urls:
            html = await self._fetch(url)
            if html:
                try:
                    soup = BeautifulSoup(html, 'html.parser')
                    text += soup.get_text(separator=' ', strip=True) + "\n"
                except: pass

        if text:
            codes = re.findall(r'\b[A-Z0-9]{4,10}\b', text)
            codes = list(set([c for c in codes if c not in ["HTTP", "HTTPS", "HTML", "PHP", "API"]]))
            if codes:
                result = "🎟️ <b>کدهای تخفیف اسنپ فود پیدا شد:</b>\n\n"
                for c in codes[:5]:
                    result += f"• <code>{c}</code>\n"
                result += "\n📌 این کدها از سایت‌های معتبر تخفیف‌یاب استخراج شده‌اند."
                return result
            else:
                return "📝 متأسفانه کد فعالی در سایت‌های منبع پیدا نشد. معمولاً کدها شخصی هستند یا منقضی شده‌اند."

        return "⚠️ خطا در دریافت کدهای تخفیف."

    async def _search_general(self, query: str) -> str:
        try:
            results = await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=5)))
            if not results:
                return "نتیجه‌ای پیدا نشد."
            context = "\n".join([f"- {r.get('title')}: {r.get('body')}" for r in results])
            return context
        except Exception as e:
            logger.error(f"DDGS error: {e}")
            return "خطا در جستجو."

    async def process(self, query: str) -> str:
        q = query.lower()
        if "قیمت دلار" in q or "دلار چنده" in q or "تتر" in q:
            return await self._get_dollar_price()
        elif "تخفیف اسنپ" in q or "کد تخفیف" in q:
            return await self._get_snapp_discounts()
        else:
            return await self._search_general(query)

_agent_search_service = None
def get_agent_search_service() -> AgentSearchService:
    global _agent_search_service
    if _agent_search_service is None:
        _agent_search_service = AgentSearchService()
    return _agent_search_service
