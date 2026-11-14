"""ULTRA INTELLIGENT SEARCH AI - Agentic Search Implementation."""

import logging
import asyncio
import httpx
import re
from bs4 import BeautifulSoup
from ddgs import DDGS
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

class AgentSearchService:
    def __init__(self):
        self.ai_service = get_ai_service()

    async def _analyze_intent(self, query: str) -> str:
        """تشخیص نیت کاربر (قیمت، کد تخفیف، اخبار یا عمومی)"""
        q = query.lower()
        if any(k in q for k in ["دلار", "طلا", "قیمت", "بیت کوین", "تتر"]):
            return "price"
        if any(k in q for k in ["کد", "تخفیف", "اسنپ", "دیجی"]):
            return "discount"
        if any(k in q for k in ["اخبار", "جدید", "امروز"]):
            return "news"
        return "general"

    async def _generate_queries(self, query: str, intent: str) -> list[str]:
        """تولید کوئری‌های هوشمند بر اساس نیت"""
        if intent == "price":
            return ["قیمت دلار آزاد امروز", "نرخ دلار بازار تهران", "USD to IRR free market", f"{query} لحظه‌ای"]
        elif intent == "discount":
            return ["کد تخفیف اسنپ فود امروز", "کد تخفیف دیجی کالا جدید", "snapfood promo code today", "آخرین کدهای تخفیف اسنپ فود"]
        elif intent == "news":
            return [f"{query} خبر", f"{query} امروز", f"latest news about {query}"]
        
        # اگر نیت عمومی بود، از AI می‌خوایم کوئری بهینه بده
        prompt = f"بهترین و کوتاه‌ترین کوئری جستجو برای این سوال چیست: '{query}'؟ فقط خود کوئری را بنویس."
        try:
            opt, _ = await self.ai_service.ask(user_message=prompt, user_name="Optimizer")
            return [opt.strip(), query, query + " چیست"]
        except:
            return [query, query + " پاسخ"]

    async def _extract_numbers_from_text(self, text: str) -> list[str]:
        """شکار اعداد قیمت (فارسی و انگلیسی)"""
        patterns = [
            r'\b([۰-۹]{2,3}[,،.][۰-۹]{3})\b', # ۸۵,۲۰۰
            r'\b([0-9]{2,3}[,،.][0-9]{3})\b', # 85,200
            r'\b([0-9]{5,7})\b',              # 85000
            r'\b([۰-۹]{5,7})\b'               # ۸۵۰۰۰
        ]
        found = []
        for p in patterns:
            found.extend(re.findall(p, text))
        return list(dict.fromkeys(found))[:6]

    async def _extract_codes_from_text(self, text: str) -> list[str]:
        """شکار کدهای تخفیف (حروف بزرگ و اعداد)"""
        # الگوی رایج کدها: ۴ تا ۱۲ کاراکتر، شامل حروف و اعداد
        pattern = r'\b[A-Z0-9]{4,12}\b'
        codes = re.findall(pattern, text)
        blacklist = ["HTTP", "HTTPS", "HTML", "PHP", "TRUE", "FALSE", "NULL"]
        return list(dict.fromkeys([c for c in codes if c not in blacklist]))[:5]

    async def _scrape_url(self, url: str) -> str:
        """استخراج متن از یک لینک"""
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                
                def parse(html):
                    soup = BeautifulSoup(html, 'html.parser')
                    for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                        tag.decompose()
                    return " ".join(list(soup.stripped_strings))[:3000]
                
                return await asyncio.to_thread(parse, resp.text)
        except:
            return ""

    async def execute_agentic_search(self, query: str, user_id: int = 0) -> str:
        """چرخه کامل جستجوی خودمختار"""
        
        # ۱. تحلیل نیت
        intent = await self._analyze_intent(query)
        logger.info(f"🤖 Agent Search - Intent: {intent} | Query: {query}")

        # ۲. تولید کوئری‌ها
        queries = await self._generate_queries(query, intent)
        
        # ۳. جستجوی موازی
        all_results = []
        for q in queries:
            try:
                # اگر سرچ داخلی DDGS خطا داد، به بعدی میره
                res = await asyncio.to_thread(lambda q=q: list(DDGS().text(q, max_results=4)))
                all_results.extend(res)
            except Exception as e:
                logger.warning(f"Search failed for '{q}': {e}")
                continue
        
        if not all_results:
            return "⚠️ متأسفانه سرورهای جستجو در حال حاضر پاسخ نمی‌دهند. لطفاً کمی بعد تلاش کنید."

        # ۴. حذف تکراری‌ها
        seen = set()
        unique = []
        for r in all_results:
            href = r.get("href", "")
            if href and href not in seen:
                seen.add(href)
                unique.append(r)

        # ۵. استخراج از Snippet (متن خلاصه گوگل) - مهم‌ترین بخش!
        all_snippets = "\n".join([r.get("body", "") for r in unique])
        
        # ۶. اسکرپ ۲ سایت اول
        scraped_text = ""
        tasks = [self._scrape_url(r.get("href")) for r in unique[:2] if r.get("href")]
        if tasks:
            texts = await asyncio.gather(*tasks)
            scraped_text = "\n\n".join([t for t in texts if t])

        # ۷. استخراج داده‌های ساختاریافته
        full_text = all_snippets + "\n" + scraped_text
        extracted_numbers = await self._extract_numbers_from_text(full_text)
        extracted_codes = await self._extract_codes_from_text(all_snippets) # کدها معمولا تو snippet هستن

        # ۸. آماده‌سازی Context نهایی
        context = ""
        if extracted_numbers:
            context += f"💰 اعداد قیمت پیدا شده: {', '.join(extracted_numbers)}\n"
        if extracted_codes:
            context += f"🎟️ کدهای تخفیف پیدا شده: {', '.join(extracted_codes)}\n"
        
        context += "\n📌 خلاصه نتایج وب:\n"
        for i, r in enumerate(unique[:5]):
            context += f"{i+1}. {r.get('title')}: {r.get('body')}\n"
        
        if scraped_text:
            context += f"\n📄 متن سایت‌ها:\n{scraped_text[:2000]}"

        # ۹. پرامپت نهایی برای تولید پاسخ
        prompt = (
            f"سوال کاربر: {query}\n\n"
            f"اطلاعات جمع‌آوری شده توسط سیستم جستجوی خودمختار:\n{context}\n\n"
            f"🚨 قانون طلایی: تو یک AI Agent هستی. اطلاعات بالا رو همین الان از اینترنت گرفتی. "
            f"اگر عدد قیمت یا کد تخفیفی در اطلاعات بالا هست، حتماً باید اون رو به کاربر بدی. "
            f"هرگز نگو 'دسترسی ندارم' یا 'پیدا نکردم' اگر اطلاعاتی وجود داره. "
            f"اگر واقعاً هیچ اطلاعاتی نبود، بگو 'من تمام منابع رو بررسی کردم اما اطلاعات دقیقی پیدا نشد.' "
            f"پاسخ رو به فارسی روان و با تگ‌های HTML بنویس."
        )

        answer, _ = await self.ai_service.ask(
            user_message=prompt,
            user_name="AI Agent",
            user_id=user_id,
            custom_system_prompt="You are an autonomous AI search agent. You have live data. Extract exact prices or codes. NEVER say you don't have internet access. Format with HTML."
        )
        
        return answer

_agent_search_service = None
def get_agent_search_service() -> AgentSearchService:
    global _agent_search_service
    if _agent_search_service is None:
        _agent_search_service = AgentSearchService()
    return _agent_search_service
