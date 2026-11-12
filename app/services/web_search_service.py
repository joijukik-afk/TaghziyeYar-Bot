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
                texts = [p.get_text(strip=True) for p in main_content.find_all(['p', 'li', 'h2', 'h3']) if len(p.get_text(strip=True)) > 20]
                return "\n".join(texts)[:3000]

            return await asyncio.to_thread(parse_html, html)
        except Exception as e:
            logger.warning(f"Extract failed {url}: {e}")
            return ""

    async def _generate_queries(self, original_query: str) -> List[str]:
        """تولید کوئری مخصوص بازار ایران"""
        prompt = (
            f"User query: '{original_query}'\n"
            "Generate exactly 2 search queries to find the most accurate live price or info. "
            "If it's about Iranian prices (dollar, gold, coin), YOU MUST include 'قیمت بازار آزاد تهران' or 'tgju' in queries. "
            "Return ONLY the queries separated by newline."
        )
        try:
            res, _ = await self.ai_service.ask(user_message=prompt, custom_system_prompt="Output only queries.")
            queries = [q.strip() for q in res.split('\n') if q.strip()]
            return (queries + [original_query])[:3]
        except:
            return [original_query, f"قیمت {original_query} بازار آزاد"]

    async def search_text(self, query: str, max_results: int = 4) -> List[Dict[str, Any]]:
        """جستجوی متنی با مدیریت خطای کامل"""
        try:
            # استفاده از to_thread چون ddgs بلاک‌کننده است
            return await asyncio.to_thread(lambda: list(DDGS().text(query, max_results=max_results)))
        except Exception as e:
            logger.warning(f"Text search error for '{query}': {e}")
            return []

    async def search_news(self, query: str, max_results: int = 2) -> List[Dict[str, Any]]:
        """جستجوی خبری با مدیریت خطای کامل"""
        try:
            return await asyncio.to_thread(lambda: list(DDGS().news(query, max_results=max_results)))
        except Exception as e:
            logger.warning(f"News search error for '{query}': {e}")
            return []

    async def search_images(self, query: str, max_results: int = 4) -> List[str]:
        try:
            results = await asyncio.to_thread(lambda: list(DDGS().images(query, max_results=max_results)))
            valid = [img.get("image") for img in results if img.get("image", "").startswith("http")]
            
            if not valid:
                en_q = "US Dollar banknote" if "دلار" in query else "Gold bars" if "طلا" in query else query
                results_en = await asyncio.to_thread(lambda: list(DDGS().images(en_q, max_results=max_results)))
                valid = [img.get("image") for img in results_en if img.get("image", "").startswith("http")]
            return valid[:4]
        except Exception as e:
            logger.warning(f"Image search error: {e}")
            return []

    async def search_and_answer(self, query: str, user_id: int = 0) -> Dict[str, Any]:
        try:
            queries = await self._generate_queries(query)
            logger.info(f"Search queries generated: {queries}")
            
            text_results, news_results = [], []
            for q in queries:
                text_results.extend(await self.search_text(q))
                news_results.extend(await self.search_news(q))

            # حذف تکراری‌ها
            unique_results = []
            seen = set()
            for r in text_results:
                if r.get("href") and r.get("href") not in seen:
                    seen.add(r.get("href"))
                    unique_results.append(r)

            # استخراج متن
            extracted_content = ""
            tasks = [self._extract_text_from_url(r.get("href")) for r in unique_results[:2]]
            if tasks:
                texts = await asyncio.gather(*tasks, return_exceptions=True)
                extracted_content = "\n\n".join([t for t in texts if isinstance(t, str) and t])

            images = await self.search_images(query)

            # ساخت Context
            context = ""
            if unique_results:
                context += "\n".join([f"- {r.get('title')}: {r.get('body')}" for r in unique_results[:5]])
            if extracted_content:
                context += f"\n\nمتن کامل:\n{extracted_content}"
            if news_results:
                context += "\n\nاخبار:\n" + "\n".join([f"- {n.get('title')}: {n.get('body')}" for n in news_results[:3]])

            # پرامپت قدرتمند (حتی اگر سرچ خالی باشد، حدس می‌زند)
            search_system_prompt = (
                "You are a helpful search assistant. "
                "If the user asks for a price (like Dollar, Gold, Bitcoin), and the web context doesn't have the EXACT live price, "
                "YOU MUST NOT SAY 'I cannot find it'. Instead, you MUST use your own internal knowledge to give the MOST RECENT estimated price you know. "
                "Always add this disclaimer: '⚠️ این قیمت تقریبی است و ممکن است تغییر کرده باشد. برای قیمت لحظه‌ای به منابع معتبر مراجعه کنید.' "
                "Answer in Persian. Use Telegram HTML tags (<b>, <code>, <blockquote>). Never use markdown."
            )

            prompt = f"سوال کاربر: {query}\n\nاطلاعات وب:\n{context}\n\nپاسخ دقیق:"

            answer_tuple = await self.ai_service.ask(
                user_message=prompt, user_name="جستجوگر", user_id=user_id, custom_system_prompt=search_system_prompt
            )
            
            answer_text = answer_tuple[0] if isinstance(answer_tuple, tuple) else str(answer_tuple)

            return {
                "text": answer_text,
                "images": images,
                "sources": [r.get("href") for r in unique_results[:3] if r.get("href")]
            }
            
        except Exception as e:
            # اگر کل فرآیند خطا داد، حداقل یک پیام دوستانه بده
            logger.error(f"Critical search error: {e}", exc_info=True)
            return {
                "text": "😔 متأسفانه در جستجو خطایی رخ داد. لطفاً دوباره تلاش کنید.",
                "images": [],
                "sources": []
            }

_web_search_service = None
def get_web_search_service() -> WebSearchService:
    global _web_search_service
    if _web_search_service is None: _web_search_service = WebSearchService()
    return _web_search_service
