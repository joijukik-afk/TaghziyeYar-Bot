"""Advanced Web search service with real-time APIs."""

import logging
import asyncio
import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

class WebSearchService:
    def __init__(self):
        self.ai_service = get_ai_service()

    async def _get_live_prices(self) -> str:
        prices = []
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # نوبیتکس برای قیمت تتر (دلار آزاد)
                resp = await client.get("https://api.nobitex.ir/v2/orderbook/USDTIRT")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "ok":
                        toman = int(float(data.get("lastTradePrice", 0)) / 10)
                        prices.append(f"دلار (تتر): {toman:,} تومان")
        except Exception as e:
            logger.warning(f"Live price API failed: {e}")
        return "\n".join(prices)

    async def _extract_text_from_url(self, url: str) -> str:
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text

            def parse_html(html_text):
                soup = BeautifulSoup(html_text, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                    tag.decompose()
                main = soup.find('main') or soup.find('article') or soup.body
                if not main: return ""
                texts = [p.get_text(strip=True) for p in main.find_all(['p', 'li', 'h2']) if len(p.get_text(strip=True)) > 30]
                return "\n".join(texts)[:2500]
            return await asyncio.to_thread(parse_html, html)
        except Exception:
            return ""

    async def search_and_answer(self, query: str, user_id: int = 0) -> str:
        # ۱. گرفتن قیمت لحظه‌ای در صورت نیاز
        live_data = ""
        if any(k in query for k in ["قیمت", "دلار", "طلا", "تتر", "بیت کوین"]):
            live_data = await self._get_live_prices()

        # ۲. جستجوی وب
        try:
            results = await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=4)))
        except Exception:
            results = []

        # ۳. خواندن متن سایت‌ها
        extracted = ""
        if results:
            tasks = [self._extract_text_from_url(r.get("href")) for r in results[:2] if r.get("href")]
            texts = await asyncio.gather(*tasks)
            extracted = "\n\n".join([t for t in texts if t])

        # ۴. آماده‌سازی اطلاعات
        context = ""
        if live_data:
            context += f"📌 اطلاعات لحظه‌ای:\n{live_data}\n\n"
        if results:
            context += "📌 نتایج وب:\n"
            for r in results:
                context += f"- {r.get('title')}: {r.get('body')}\n"
        if extracted:
            context += f"\n📄 متن مقالات:\n{extracted}"

        if not context.strip():
            context = "اطلاعاتی پیدا نشد. از دانش خودت استفاده کن."

        # ۵. پاسخ نهایی
        prompt = (
            f"سوال کاربر: {query}\n\n"
            f"اطلاعات جدید از وب:\n{context}\n\n"
            f"🚨 قانون: اگر قیمت در متن بالا بود، دقیقاً همان را بگو. اگر اطلاعات وب ناقص بود، از دانش خودت استفاده کن و بگو شاید قدیمی باشد. "
            f"پاسخ به فارسی روان و با تگ‌های HTML."
        )

        answer, _ = await self.ai_service.ask(
            user_message=prompt, user_name="جستجوگر", user_id=user_id,
            custom_system_prompt="You are a smart assistant. Prioritize the provided context. Answer in Persian with HTML formatting."
        )
        return answer

_web_search_service = None
def get_web_search_service() -> WebSearchService:
    global _web_search_service
    if _web_search_service is None: _web_search_service = WebSearchService()
    return _web_search_service
