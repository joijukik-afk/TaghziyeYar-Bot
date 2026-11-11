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
                paragraphs = main_content.find_all('p')
                text = "\n".join([p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30])
                return text[:2000]

            return await asyncio.to_thread(parse_html, html)
        except Exception as e:
            logger.warning(f"Failed to extract text from {url}: {e}")
            return ""

    async def search_text(self, query: str, max_results: int = 6) -> List[Dict[str, Any]]:
        try: return await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=max_results)))
        except Exception as e: logger.warning(f"Text search error: {e}"); return []

    async def search_news(self, query: str, max_results: int = 3) -> List[Dict[str, Any]]:
        try: return await asyncio.to_thread(lambda: list(DDGS().news(query, max_results=max_results)))
        except Exception as e: logger.warning(f"News search error: {e}"); return []

    async def search_images(self, query: str, max_results: int = 4) -> List[str]:
        try:
            results = await asyncio.to_thread(lambda: list(DDGS().images(query, max_results=max_results)))
            return [img.get("image") for img in results if img.get("image")]
        except Exception as e: logger.warning(f"Image search error: {e}"); return []

    async def search_and_answer(self, query: str, user_id: int = 0) -> Dict[str, Any]:
        text_results, news_results, images = await asyncio.gather(
            self.search_text(query, max_results=5),
            self.search_news(query, max_results=2),
            self.search_images(query, max_results=4)
        )

        extracted_content = ""
        tasks = [self._extract_text_from_url(res.get("href")) for res in text_results[:2] if res.get("href")]
        if tasks:
            texts = await asyncio.gather(*tasks)
            extracted_content = "\n\n".join([t for t in texts if t])

        context_parts = []
        if text_results:
            context_parts.append("📌 نتایج جستجوی وب:")
            for i, res in enumerate(text_results):
                context_parts.append(f"{i+1}. {res.get('title', '')}\n{res.get('body', '')}")
        if news_results:
            context_parts.append("\n📰 اخبار مرتبط:")
            for i, news in enumerate(news_results):
                context_parts.append(f"{i+1}. {news.get('title', '')} ({news.get('source', '')})\n{news.get('body', '')}")
        if extracted_content: context_parts.append(f"\n📄 متن کامل مقالات:\n{extracted_content}")

        full_context = "\n\n".join(context_parts)
        if not full_context.strip():
            full_context = "⚠️ جستجوی اینترنتی نتیجه‌ای برنگرداند (محدودیت سرور). لطفاً از دانش داخلی خودت استفاده کن."

        search_system_prompt = (
            "You are an expert AI search assistant. Answer the user's question accurately. "
            "You are a general-purpose smart assistant. "
            "Answer in Persian using HTML tags like <b>. "
            "If the web search context is empty, USE YOUR OWN INTERNAL KNOWLEDGE. Never refuse to answer."
        )

        prompt = f"سوال کاربر: {query}\n\nاطلاعات جمع‌آوری شده:\n{full_context}\n\nپاسخ تو:"

        answer_tuple = await self.ai_service.ask(
            user_message=prompt, user_name="جستجوگر", user_id=user_id, custom_system_prompt=search_system_prompt
        )
        
        answer_text = answer_tuple[0] if isinstance(answer_tuple, tuple) else str(answer_tuple)

        return {
            "text": answer_text,
            "images": images,
            "sources": [res.get("href") for res in text_results[:3] if res.get("href")]
        }

_web_search_service: Optional[WebSearchService] = None

def get_web_search_service() -> WebSearchService:
    global _web_search_service
    if _web_search_service is None: _web_search_service = WebSearchService()
    return _web_search_service
