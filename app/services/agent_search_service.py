"""Agent Search Service - Simple & Resilient Version."""

import logging
import asyncio
import httpx
from typing import Optional
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

class AgentSearchService:
    def __init__(self):
        self.ai_service = get_ai_service()

    async def _get_tgju_prices(self) -> Optional[str]:
        """دریافت قیمت از API TGJU"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.tgju.org/v1/market/indicator/summary-table-data",
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                logger.info(f"TGJU API status: {resp.status_code}")
                
                if resp.status_code == 200:
                    data = resp.json()
                    prices = []
                    for item in data.get("data", []):
                        symbol = item.get("symbol", "")
                        value = item.get("value", 0)
                        if symbol == "price_dollar_rl":
                            prices.append(f"💰 دلار: <b>{value:,}</b> تومان")
                        elif symbol == "geram18":
                            prices.append(f"🥇 طلا (گرم): <b>{value:,}</b> تومان")
                    if prices:
                        return "\n".join(prices) + "\n\n📊 منبع: TGJU (لحظه‌ای)"
        except Exception as e:
            logger.error(f"TGJU API failed: {e}")
        return None

    async def execute_agentic_search(self, query: str, user_id: int = 0) -> str:
        """جستجوی ساده و مقاوم"""
        try:
            # ۱. اگه درباره قیمت بود، از TGJU بگیر
            if any(k in query.lower() for k in ["قیمت", "دلار", "طلا", "سکه", "تتر"]):
                prices = await self._get_tgju_prices()
                if prices:
                    return prices
                else:
                    return "⚠️ متأسفانه سرور TGJU در حال حاضر پاسخ نمی‌دهد. لطفاً چند لحظه بعد دوباره تلاش کنید."
            
            # ۲. برای بقیه سوالات، از AI کمک بگیر (بدون جستجوی اینترنتی)
            return ""
            
        except Exception as e:
            logger.error(f"Search error: {e}", exc_info=True)
            raise e  # خطا رو می‌فرستیم تا توی search_commands نمایش داده بشه

_agent_search_service = None
def get_agent_search_service() -> AgentSearchService:
    global _agent_search_service
    if _agent_search_service is None:
        _agent_search_service = AgentSearchService()
    return _agent_search_service
