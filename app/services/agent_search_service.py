# app/services/agent_search_service.py
import logging
import asyncio
import httpx
import re
from typing import Optional
from ddgs import DDGS
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

class AgentSearchService:
    def __init__(self):
        self.ai_service = get_ai_service()

    async def _try_wallex(self) -> Optional[str]:
        """منبع ۱: Wallex API"""
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get("https://api.wallex.ir/v1/markets")
                if resp.status_code == 200:
                    data = resp.json()
                    symbols = data.get("result", {}).get("symbols", {})
                    if "USDTIRT" in symbols:
                        price = symbols["USDTIRT"].get("stats", {}).get("lastPrice", 0)
                        if price and float(price) > 0:
                            logger.info(f"✅ Wallex worked: {price}")
                            return f"💰 <b>دلار (تتر):</b> {int(float(price)):,} تومان\n📊 منبع: Wallex"
        except Exception as e:
            logger.warning(f"Wallex failed: {e}")
        return None

    async def _try_bitpin(self) -> Optional[str]:
        """منبع ۲: Bitpin API"""
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get("https://api.bitpin.ir/api/v1/mkt/markets/")
                if resp.status_code == 200:
                    data = resp.json()
                    for m in data.get("results", []):
                        if m.get("code") == "USDT_IRT":
                            price = m.get("price", 0)
                            if price and float(price) > 0:
                                logger.info(f"✅ Bitpin worked: {price}")
                                return f"💰 <b>دلار (تتر):</b> {int(float(price)):,} تومان\n📊 منبع: Bitpin"
        except Exception as e:
            logger.warning(f"Bitpin failed: {e}")
        return None

    def _extract_price_from_text(self, text: str) -> Optional[int]:
        """استخراج عدد قیمت از متن (پشتیبانی از اعداد فارسی و انگلیسی)"""
        patterns = [
            r'([۰-۹]{2,3}[,،.][۰-۹]{3})',  # ۲۶۵,۰۰۰
            r'([0-9]{2,3}[,،.][0-9]{3})',  # 265,000
            r'([0-9]{5,7})',               # 265000
            r'([۰-۹]{5,7})'                # ۲۶۵۰۰۰
        ]
        for p in patterns:
            match = re.search(p, text)
            if match:
                num_str = match.group(1).replace(",", "").replace("،", "").replace(".", "")
                # تبدیل اعداد فارسی به انگلیسی
                num_str = num_str.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
                try:
                    return int(num_str)
                except:
                    continue
        return None

    async def _search_google_for_price(self) -> Optional[str]:
        """جستجو در گوگل (DDGS) و استخراج قیمت از Snippet نتایج"""
        queries = [
            "قیمت دلار امروز",
            "قیمت دلار آزاد",
            "نرخ دلار تهران",
            "USD to IRR price today"
        ]
        
        for query in queries:
            try:
                logger.info(f"🔍 Searching Google for: {query}")
                results = await asyncio.to_thread(lambda q=query: list(DDGS().text(q, max_results=8)))
                
                for res in results:
                    body = res.get("body", "")
                    title = res.get("title", "")
                    full_text = title + " " + body
                    
                    price = self._extract_price_from_text(full_text)
                    if price and 100000 < price < 500000:  # فیلتر منطقی قیمت دلار
                        logger.info(f"✅ Extracted price from Google: {price}")
                        return (
                            f"💰 <b>قیمت دلار:</b> {price:,} تومان\n"
                            f"📊 منبع: {res.get('title', 'جستجوی گوگل')}\n"
                            f"🔗 {res.get('href', '')}"
                        )
            except Exception as e:
                logger.warning(f"Google search failed for '{query}': {e}")
                continue
        return None

    async def _get_dollar_price(self) -> Optional[str]:
        """امتحان همه منابع به ترتیب"""
        logger.info("🔄 Trying to fetch dollar price...")
        
        # ۱. Wallex (API)
        result = await self._try_wallex()
        if result: return result
        
        # ۲. Bitpin (API)
        result = await self._try_bitpin()
        if result: return result
        
        # ۳. جستجوی گوگل و استخراج از Snippet
        result = await self._search_google_for_price()
        if result: return result
        
        logger.error("❌ All price sources failed!")
        return None

    async def execute_agentic_search(self, query: str, user_id: int = 0) -> str:
        """جستجوی هوشمند چندمنبعی"""
        try:
            if any(k in query.lower() for k in ["قیمت", "دلار", "تتر", "usdt", "dollar", "طلا", "سکه"]):
                prices = await self._get_dollar_price()
                if prices:
                    return prices
                else:
                    return (
                        "⚠️ متأسفانه در این لحظه امکان دریافت قیمت از منابع آنلاین وجود ندارد.\n\n"
                        "💡 لطفاً قیمت را از سایت‌های زیر چک کنید:\n"
                        "• TGJU.org\n"
                        "• Bonbast.com\n"
                        "• Alanchand.com"
                    )
            
            return ""
            
        except Exception as e:
            logger.error(f"Search error: {e}", exc_info=True)
            raise e

_agent_search_service = None
def get_agent_search_service() -> AgentSearchService:
    global _agent_search_service
    if _agent_search_service is None:
        _agent_search_service = AgentSearchService()
    return _agent_search_service
