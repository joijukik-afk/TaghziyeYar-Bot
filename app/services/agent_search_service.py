# app/services/agent_search_service.py
import logging
import asyncio
import httpx
import json
from typing import Optional, Dict, Any
from app.services.ai_service import get_ai_service
from app.services.iranian_scraper import get_iranian_scraper

logger = logging.getLogger(__name__)

# URL یک نمونه API عمومی برای TGJU (برای دریافت قیمت‌ها بدون نیاز به MCP)
TGJU_API_URL = "https://api.tgju.org/v1/market/indicator/summary-table-data"

class AgentSearchService:
    def __init__(self):
        self.ai_service = get_ai_service()
        self.scraper = get_iranian_scraper()

    async def _get_tgju_prices(self) -> Optional[str]:
        """دریافت قیمت‌های لحظه‌ای از TGJU از طریق API عمومی."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # این API عمومی ممکن است به کلید نیاز نداشته باشد
                resp = await client.get(TGJU_API_URL)
                resp.raise_for_status()
                data = resp.json()
                
                # استخراج قیمت دلار، طلا و سکه از ساختار JSON
                # ساختار دقیق باید بررسی شود، اما این یک نمونه است
                prices = []
                for item in data.get("data", []):
                    if item.get("symbol") == "price_dollar_rl":
                        prices.append(f"💰 دلار: {item['value']:,} تومان")
                    elif item.get("symbol") == "geram18":
                        prices.append(f"🥇 طلا (گرم): {item['value']:,} تومان")
                
                if prices:
                    return "\n".join(prices) + "\n\n📊 منبع: TGJU (لحظه‌ای)"
        except Exception as e:
            logger.error(f"TGJU API failed: {e}")
        return None

    async def _search_iranian_web(self, query: str) -> Optional[str]:
        """جستجوی مستقیم در وب ایرانی با استفاده از IranianScraper."""
        # برای سادگی، یک URL جستجوی عمومی (مثلاً ترب) را امتحان می‌کنیم
        # در عمل، می‌توانید URLهای دیگری را بر اساس نیت کاربر انتخاب کنید
        search_url = f"https://www.torob.com/search/?q={query}"
        content = self.scraper.fetch_page_content(search_url)
        if content:
            return f"اطلاعات از وب ایرانی:\n{content[:2000]}"
        return None

    async def execute_agentic_search(self, query: str, user_id: int = 0) -> str:
        """اجرای جستجوی خودمختار و چندمنبعی."""
        
        # ۱. اگر سوال درباره قیمت است، از TGJU استفاده کن
        if any(k in query.lower() for k in ["قیمت", "دلار", "طلا", "سکه", "بیت کوین"]):
            price_data = await self._get_tgju_prices()
            if price_data:
                return price_data

        # ۲. جستجوی مستقیم در وب ایرانی با استفاده از اسکرپر
        iranian_web_context = await self._search_iranian_web(query)
        if iranian_web_context:
            return iranian_web_context

        # ۳. اگر همه چیز شکست خورد، به هوش مصنوعی بگو از دانش خودش استفاده کند
        logger.info("All search methods failed. Falling back to AI internal knowledge.")
        return ""

# نمونه سراسری
_agent_search_service = None
def get_agent_search_service() -> AgentSearchService:
    global _agent_search_service
    if _agent_search_service is None:
        _agent_search_service = AgentSearchService()
    return _agent_search_service
