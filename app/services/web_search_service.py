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

    async def _extract_text_from_url(self, url: str) -> str:
        """استخراج متن اصلی از یک URL با استفاده از httpx و BeautifulSoup"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text

            # پردازش در ترد جداگانه تا ربات هنگ نکند
            def parse_html(html_text):
                soup = BeautifulSoup(html_text, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                    tag.decompose()
                main_content = soup.find('main') or soup.find('article') or soup.body
                if not main_content:
                    return ""
                paragraphs = main_content.find_all('p')
                return "\n".join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])[:3000]

            return await asyncio.to_thread(parse_html, html)
        except Exception as e:
            logger.warning(f"Failed to extract text from {url}: {e}")
            return ""

    async def search_text(self, query: str, max_results: int = 4) -> List[Dict[str, Any]]:
        """جستجوی متنی در وب"""
        try:
            return await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=max_results)))
        except Exception as e:
            logger.warning(f"Text search error: {e}")
            return []

    async def search_news(self, query: str, max_results: int = 3) -> List[Dict[str, Any]]:
        """جستجوی اخبار"""
        try:
            return await asyncio.to_thread(lambda: list(DDGS().news(query, max_results=max_results)))
        except Exception as e:
            logger.warning(f"News search error: {e}")
            return []

    async def search_images(self, query: str, max_results: int = 3) -> List[Dict[str, Any]]:
        """جستجوی تصویر"""
        try:
            return await asyncio.to_thread(lambda: list(DDGS().images(query, max_results=max_results)))
        except Exception as e:
            logger.warning(f"Image search error: {e}")
            return []

    async def search_and_answer(self, query: str, user_id: int = 0) -> Dict[str, Any]:
        """جستجوی جامع و تولید پاسخ نهایی با هوش مصنوعی."""
        # ۱. جستجوی متنی و خبری به صورت موازی
        text_results, news_results = await asyncio.gather(
            self.search_text(query, max_results=4),
            self.search_news(query, max_results=3)
        )

        # ۲. استخراج متن کامل از ۱ نتیجه اول
        extracted_content = ""
        if text_results and len(text_results) > 0:
            first_url = text_results[0].get("href")
            if first_url:
                extracted_content = await self._extract_text_from_url(first_url)

        # ۳. آماده‌سازی Context
        context_parts = []
        
        if text_results:
            context_parts.append("📌 نتایج جستجوی وب:")
            for i, res in enumerate(text_results):
                title = res.get("title", "")
                body = res.get("body", "")
                href = res.get("href", "")
                context_parts.append(f"{i+1}. {title}\n{body}\nمنبع: {href}")

        if news_results:
            context_parts.append("\n📰 اخبار مرتبط:")
            for i, news in enumerate(news_results):
                title = news.get("title", "")
                body = news.get("body", "")
                source = news.get("source", "")
                context_parts.append(f"{i+1}. {title} ({source})\n{body}")

        if extracted_content:
            context_parts.append(f"\n📄 متن کامل از منبع اول:\n{extracted_content}")

        full_context = "\n\n".join(context_parts)
        
        if len(full_context) > 6000:
            full_context = full_context[:6000] + "\n...(متن کوتاه شد)"

        # ۴. تولید پاسخ نهایی با هوش مصنوعی (درخواست خروجی HTML)
        prompt = (
            f"بر اساس اطلاعات زیر، به سوال کاربر پاسخ دقیق، جامع و مفید بده. "
            f"اگر اطلاعات کافی نبود، صادقانه بگو. پاسخ باید به زبان فارسی باشد.\n"
            f"از تگ‌های HTML مثل <b> و <i> برای خوانایی بهتر استفاده کن.\n\n"
            f"سوال کاربر: {query}\n\n"
            f"اطلاعات جمع‌آوری شده:\n{full_context}\n\n"
            f"پاسخ تو:"
        )

        answer_tuple = await self.ai_service.ask(
            user_message=prompt,
            user_name="جستجوگر",
            user_id=user_id
        )
        
        answer_text = answer_tuple[0] if isinstance(answer_tuple, tuple) else str(answer_tuple)

        # ۵. جستجوی تصویر
        images = []
        try:
            img_results = await self.search_images(query, max_results=3)
            images = [img.get("image") for img in img_results if img.get("image")]
        except Exception as e:
            logger.warning(f"Image search failed: {e}")

        return {
            "text": answer_text,
            "images": images,
            "sources": [res.get("href") for res in text_results[:2] if res.get("href")]
        }


_web_search_service: Optional[WebSearchService] = None

def get_web_search_service() -> WebSearchService:
    global _web_search_service
    if _web_search_service is None:
        _web_search_service = WebSearchService()
    return _web_search_service
