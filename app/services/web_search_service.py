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
        """استخراج متن کامل از یک URL"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                html = resp.text

            def parse_html(html_text):
                soup = BeautifulSoup(html_text, 'html.parser')
                for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe']):
                    tag.decompose()
                main_content = soup.find('main') or soup.find('article') or soup.body
                if not main_content: return ""
                # استخراج متن از پاراگراف‌ها و لیست‌ها
                texts = []
                for elem in main_content.find_all(['p', 'li', 'h1', 'h2', 'h3', 'span']):
                    t = elem.get_text(strip=True)
                    if len(t) > 20: texts.append(t)
                return "\n".join(texts)[:3000] # ۳۰۰۰ کاراکتر از هر سایت

            return await asyncio.to_thread(parse_html, html)
        except Exception as e:
            logger.warning(f"Failed to extract text from {url}: {e}")
            return ""

    async def _generate_queries(self, original_query: str) -> List[str]:
        """تولید چند کوئری جستجوی بهتر با استفاده از AI"""
        prompt = (
            f"User query: '{original_query}'\n"
            "Generate exactly 2 optimized search engine queries (one in Persian, one in English) to find the most accurate and up-to-date information for this. "
            "Return ONLY the queries separated by a newline. No extra text."
        )
        try:
            res, _ = await self.ai_service.ask(user_message=prompt, custom_system_prompt="You are a search query optimizer. Output only queries.")
            queries = [q.strip() for q in res.split('\n') if q.strip()]
            return queries[:2] + [original_query]
        except:
            return [original_query]

    async def search_text(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        try: return await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=max_results)))
        except Exception as e: logger.warning(f"Text search error: {e}"); return []

    async def search_news(self, query: str, max_results: int = 3) -> List[Dict[str, Any]]:
        try: return await asyncio.to_thread(lambda: list(DDGS().news(query, max_results=max_results)))
        except Exception as e: logger.warning(f"News search error: {e}"); return []

    async def search_images(self, query: str, max_results: int = 4) -> List[str]:
        try:
            results = await asyncio.to_thread(lambda: list(DDGS().images(query, max_results=max_results)))
            valid_images = []
            for img in results:
                url = img.get("image", "")
                # فقط لینک‌های معتبر و با فرمت عکس
                if url and url.startswith("http") and any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    valid_images.append(url)
            return valid_images[:4]
        except Exception as e: logger.warning(f"Image search error: {e}"); return []

    async def search_and_answer(self, query: str, user_id: int = 0) -> Dict[str, Any]:
        # ۱. تولید کوئری‌های بهینه
        queries = await self._generate_queries(query)
        logger.info(f"Optimized queries: {queries}")

        # ۲. جستجوی متنی و خبری برای همه کوئری‌ها
        text_results = []
        news_results = []
        for q in queries:
            t_res = await self.search_text(q, max_results=3)
            n_res = await self.search_news(q, max_results=2)
            text_results.extend(t_res)
            news_results.extend(n_res)

        # حذف تکراری‌ها
        seen_urls = set()
        unique_text_results = []
        for r in text_results:
            url = r.get("href")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_text_results.append(r)

        # ۳. استخراج متن از ۳ سایت اول
        extracted_content = ""
        tasks = [self._extract_text_from_url(res.get("href")) for res in unique_text_results[:3] if res.get("href")]
        if tasks:
            texts = await asyncio.gather(*tasks)
            extracted_content = "\n\n".join([t for t in texts if t])

        # ۴. جستجوی عکس
        images = await self.search_images(query, max_results=4)

        # ۵. آماده‌سازی Context
        context_parts = []
        if unique_text_results:
            context_parts.append("📌 نتایج وب:")
            for i, res in enumerate(unique_text_results[:6]):
                context_parts.append(f"{i+1}. {res.get('title')} - {res.get('body')}")
        if news_results:
            context_parts.append("\n📰 اخبار:")
            for i, news in enumerate(news_results[:4]):
                context_parts.append(f"{i+1}. {news.get('title')} ({news.get('source')}) - {news.get('body')}")
        if extracted_content:
            context_parts.append(f"\n📄 متن کامل مقالات:\n{extracted_content}")

        full_context = "\n".join(context_parts)
        if len(full_context) > 8000: full_context = full_context[:8000] + "..."

        # ۶. پرامپت اختصاصی جستجوگر (بسیار دقیق برای قیمت‌ها و همه چیز)
        search_system_prompt = (
            "You are an expert AI search assistant. Answer the user's question accurately using the provided context. "
            "If the question is about a price (e.g., dollar, gold, supplements), look CAREFULLY in the context for the most recent date and price. State the date and price clearly. "
            "If the context lacks the exact answer, USE YOUR OWN KNOWLEDGE, but mention that it might not be live. "
            "Answer in Persian. Format with Telegram HTML tags: <b> for bold, <i> for italic, <code> for numbers/links, <blockquote> for important notes. "
            "Do NOT use markdown like ** or ##. "
            "Make the answer look beautiful and structured. Never say 'I am a nutritionist', you are a general assistant."
        )

        prompt = f"سوال کاربر: {query}\n\nاطلاعات استخراج شده:\n{full_context}\n\nپاسخ دقیق و کامل تو:"

        answer_tuple = await self.ai_service.ask(
            user_message=prompt, user_name="جستجوگر", user_id=user_id, custom_system_prompt=search_system_prompt
        )
        
        answer_text = answer_tuple[0] if isinstance(answer_tuple, tuple) else str(answer_tuple)

        return {
            "text": answer_text,
            "images": images,
            "sources": [res.get("href") for res in unique_text_results[:3] if res.get("href")]
        }

_web_search_service: Optional[WebSearchService] = None

def get_web_search_service() -> WebSearchService:
    global _web_search_service
    if _web_search_service is None: _web_search_service = WebSearchService()
    return _web_search_service
