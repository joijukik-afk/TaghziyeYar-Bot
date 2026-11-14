"""Real Search Service - Extracts prices/codes from DDGS snippets."""

import logging
import asyncio
import re
from typing import Optional, List, Dict
from ddgs import DDGS
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

class AgentSearchService:
    def __init__(self):
        self.ai_service = get_ai_service()

    def _extract_prices(self, text: str) -> List[str]:
        """استخراج اعداد قیمت (فارسی و انگلیسی)"""
        patterns = [
            r'([۰-۹]{2,3}[,،.][۰-۹]{3})',  # ۲۶۵,۰۰۰
            r'([0-9]{2,3}[,،.][0-9]{3})',  # 265,000
            r'([0-9]{5,7})',               # 265000
            r'([۰-۹]{5,7})'                # ۲۶۵۰۰۰
        ]
        found = []
        for p in patterns:
            found.extend(re.findall(p, text))
        return list(dict.fromkeys(found))[:10]

    def _extract_codes(self, text: str) -> List[str]:
        """استخراج کدهای تخفیف (حروف بزرگ + اعداد)"""
        pattern = r'\b[A-Z][A-Z0-9]{3,11}\b'
        codes = re.findall(pattern, text)
        blacklist = ["HTTP", "HTTPS", "HTML", "PHP", "TRUE", "FALSE", "NULL"]
        return list(dict.fromkeys([c for c in codes if c not in blacklist]))[:10]

    async def search(self, query: str) -> Dict[str, any]:
        """جستجوی واقعی و استخراج داده"""
        logger.info(f"🔍 Searching for: {query}")
        
        # ۲ تا کوئری مختلف برای نتیجه بهتر
        queries = [query]
        if "قیمت" in query or "دلار" in query:
            queries.append("قیمت دلار امروز بازار آزاد")
        if "کد" in query or "تخفیف" in query:
            queries.append("کد تخفیف جدید امروز")

        all_snippets = []
        all_urls = []
        
        for q in queries:
            try:
                results = await asyncio.to_thread(lambda q=q: list(DDGS().text(q, max_results=5)))
                for r in results:
                    body = r.get("body", "")
                    title = r.get("title", "")
                    href = r.get("href", "")
                    if body:
                        all_snippets.append(f"[{title}] {body}")
                        all_urls.append(href)
            except Exception as e:
                logger.warning(f"DDGS failed for '{q}': {e}")

        combined_text = "\n".join(all_snippets)
        
        # استخراج داده‌ها
        prices = self._extract_prices(combined_text)
        codes = self._extract_codes(combined_text)
        
        logger.info(f"✅ Found {len(prices)} prices, {len(codes)} codes, {len(all_snippets)} snippets")
        
        return {
            "snippets": combined_text,
            "prices": prices,
            "codes": codes,
            "urls": all_urls[:5]
        }

_agent_search_service = None
def get_agent_search_service() -> AgentSearchService:
    global _agent_search_service
    if _agent_search_service is None:
        _agent_search_service = AgentSearchService()
    return _agent_search_service
