"""Advanced Web search service with Deep Scraping and strict extraction."""

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
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text

            def parse_html(html_text):
                soup = BeautifulSoup(html_text, 'html.parser')
                # حذف تگ‌های غیرضروری
                for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']):
                    tag.decompose()
                
                # 👇 استخراج تمام متن‌های خالص (این متد بهترین روش برای پیدا کردن کدهای مخفی است)
                texts = list(soup.stripped_strings)
                
                # حذف متن‌های خیلی کوتاه (مثل منوها) اما نگه داشتن کدها
                filtered_texts = [t for t in texts if len(t) > 3 and len(t) < 200]
                
                # حذف تکراری‌ها
                unique_texts = list(dict.fromkeys(filtered_texts))
                return "\n".join(unique_texts)[:4000] # ۴۰۰۰ کاراکتر از هر سایت

            return await asyncio.to_thread(parse_html, html)
        except Exception as e:
            logger.warning(f"Scraping error for {url}: {e}")
            return ""

    async def search_and_answer(self, query: str, user_id: int = 0) -> str:
        # ۱. گرفتن قیمت لحظه‌ای در صورت نیاز
        live_data = ""
        if any(k in query for k in ["قیمت", "دلار", "طلا", "تتر", "بیت کوین"]):
            live_data = await self._get_live_prices()

        # ۲. جستجوی وب
        results = []
        try:
            results = await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=5)))
        except Exception as e:
            logger.warning(f"DDGS search error: {e}")

        # ۳. خواندن متن کامل از ۲ سایت اول
        extracted = ""
        if results:
            tasks = [self._extract_text_from_url(r.get("href")) for r in results[:2] if r.get("href")]
            texts = await asyncio.gather(*tasks)
            extracted = "\n\n".join([t for t in texts if t])

        # ۴. ساخت کانتکست
        context = ""
        if live_data:
            context += f"📌 قیمت لحظه‌ای:\n{live_data}\n\n"
        if results:
            context += "📌 خلاصه نتایج وب:\n"
            for r in results:
                context += f"- {r.get('title')}: {r.get('body')}\n"
        if extracted:
            context += f"\n📄 متن کامل استخراج شده از سایت‌ها (کدها و جزئیات اینجاست):\n{extracted}"

        if not context.strip():
            context = "هیچ نتیجه‌ای از وب پیدا نشد."

        # ۵. پرامپت استخراج (اجبار به استفاده از متن)
        prompt = (
            f"سوال کاربر: {query}\n\n"
            f"اطلاعات جدیدی که همین الان از اینترنت به دست آوردم:\n{context}\n\n"
            f"🚨 قانون آهنین: تو همین الان این اطلاعات رو از اینترنت گرفتی. اگر در متن بالا کد تخفیف یا قیمتی وجود داره، باید دقیقاً همون رو به کاربر بدی. هرگز نگو 'من دسترسی به اینترنت ندارم'. اگر واقعاً کدی پیدا نکردی، بگو 'جستجو کردم اما کد فعالی پیدا نکردم'. پاسخ رو به فارسی روان بنویس."
        )

        answer, _ = await self.ai_service.ask(
            user_message=prompt, 
            user_name="جستجوگر", 
            user_id=user_id,
            custom_system_prompt="You are a real-time search assistant. You have the latest web data provided to you. NEVER say you don't have internet access. Answer accurately in Persian using HTML."
        )
        return answer

_web_search_service = None
def get_web_search_service() -> WebSearchService:
    global _web_search_service
    if _web_search_service is None: _web_search_service = WebSearchService()
    return _web_search_service
