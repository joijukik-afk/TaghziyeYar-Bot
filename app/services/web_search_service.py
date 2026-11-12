"""Web search service using DuckDuckGo (ddgs) and Groq for summarization."""

import logging
import asyncio
from typing import Optional, Dict, Any, List
import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

class WebSearchService:
    def __init__(self):
        self.ai_service = get_ai_service()

    async def _get_live_dollar_price(self) -> str:
        """دریافت قیمت لحظه‌ای دلار از API نوبیتکس (تتر به تومان)"""
        try:
            async with httpx.AsyncClient() as client:
                # API نوبیتکس برای قیمت لحظه‌ای تتر (دلار)
                resp = await client.get("https://api.nobitex.ir/v2/orderbook/USDTIRT", timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "ok":
                        price_rial = float(data.get("lastTradePrice", 0))
                        price_toman = int(price_rial / 10) # تبدیل ریال به تومان
                        return f"قیمت لحظه‌ای دلار (تتر): <b>{price_toman:,} تومان</b>"
        except Exception as e:
            logger.warning(f"Live price API failed: {e}")
        return ""

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
                main_content = soup.find('main') or soup.find('article') or soup.body
                if not main_content: return ""
                texts = [p.get_text(strip=True) for p in main_content.find_all(['p', 'li', 'h2', 'h3']) if len(p.get_text(strip=True)) > 20]
                return "\n".join(texts)[:2000]

            return await asyncio.to_thread(parse_html, html)
        except Exception:
            return ""

    async def search_text(self, query: str, max_results: int = 4) -> List[Dict[str, Any]]:
        try:
            return await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=max_results)))
        except Exception as e:
            logger.warning(f"Text search error: {e}")
            return []

    async def search_images(self, query: str) -> List[str]:
        """جستجوی عکس با متد مطمئن"""
        try:
            results = await asyncio.to_thread(lambda: list(DDGS().images(query, max_results=4)))
            return [img.get("image") for img in results if img.get("image", "").startswith("http")]
        except Exception as e:
            logger.warning(f"Image search error: {e}")
            return []

    async def search_and_answer(self, query: str, user_id: int = 0) -> Dict[str, Any]:
        # ۱. بررسی اینکه آیا کاربر قیمت دلار می‌خواهد یا نه
        live_price_data = ""
        if "دلار" in query and ("قیمت" in query or "چند" in query or "نرخ" in query):
            live_price_data = await self._get_live_dollar_price()

        # ۲. سرچ متنی
        text_results = await self.search_text(query, max_results=3)
        
        extracted_content = ""
        if text_results:
            tasks = [self._extract_text_from_url(r.get("href")) for r in text_results[:2] if r.get("href")]
            texts = await asyncio.gather(*tasks)
            extracted_content = "\n".join([t for t in texts if t])

        # ۳. سرچ عکس
        images = await self.search_images(query)

        # ۴. ساخت Context (اطلاعات)
        context = ""
        if live_price_data:
            context += f"📌 اطلاعات لحظه‌ای از API:\n{live_price_data}\n\n"
        if text_results:
            context += "📌 نتایج وب:\n" + "\n".join([f"- {r.get('title')}: {r.get('body')}" for r in text_results])
        if extracted_content:
            context += f"\n\nمتن کامل:\n{extracted_content}"

        # ۵. پرامپت
        search_system_prompt = (
            "You are a smart search assistant. Answer the user's question accurately based on the context. "
            "CRITICAL: If 'اطلاعات لحظه‌ای از API' is provided in the context, YOU MUST prioritize it and use that exact number. "
            "If no live data is present and you use your internal knowledge, add a warning that it's an estimate. "
            "Answer in Persian. Use HTML tags (<b>, <code>). Never use markdown."
        )

        prompt = f"سوال کاربر: {query}\n\nاطلاعات:\n{context}\n\nپاسخ:"

        answer_tuple = await self.ai_service.ask(
            user_message=prompt, user_name="جستجوگر", user_id=user_id, custom_system_prompt=search_system_prompt
        )
        
        return {
            "text": answer_tuple[0] if isinstance(answer_tuple, tuple) else str(answer_tuple),
            "images": images,
            "sources": [r.get("href") for r in text_results[:2] if r.get("href")]
        }

_web_search_service = None
def get_web_search_service() -> WebSearchService:
    global _web_search_service
    if _web_search_service is None: _web_search_service = WebSearchService()
    return _web_search_service
