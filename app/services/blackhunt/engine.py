"""موتور اصلی BLACKHUNT — ارکستراتور."""
import asyncio, logging, time
from typing import List, Tuple
from app.services.blackhunt.models import DealResult, SearchStats, SearchIntent
from app.services.blackhunt.query_planner import plan_search
from app.services.blackhunt.adapters import MCPAdapter, TavilyWebAdapter, MCP_ENDPOINTS
from app.services.blackhunt.analyzer import analyze_deals, deduplicate, filter_by_intent
from app.services.ai_service import get_ai_service

logger = logging.getLogger(__name__)

class BlackHuntEngine:
    def __init__(self):
        self.mcp_adapters = {name: MCPAdapter(name, url) for name, url in MCP_ENDPOINTS.items()}
        self.tavily = TavilyWebAdapter()

    async def close(self):
        for adapter in self.mcp_adapters.values(): await adapter.close()

    async def search(self, user_request: str) -> Tuple[List[DealResult], SearchStats, SearchIntent]:
        start = time.time()
        intent = await plan_search(user_request)
        queries = (intent.queries or [user_request])[:3]
        all_results: List[DealResult] = []
        sources_used: List[str] = []; sources_failed: List[str] = []; q_count = 0
        tasks = []
        for q in queries:
            q_count += 1
            for name, adapter in self.mcp_adapters.items():
                tasks.append(self._safe(adapter.search, q, name, sources_used, sources_failed))
            tasks.append(self._safe(self.tavily.search, q, "tavily", sources_used, sources_failed))
        batches = await asyncio.gather(*tasks, return_exceptions=True)
        for batch in batches:
            if isinstance(batch, list): all_results.extend(batch)
        deduped = deduplicate(all_results)
        before_filter = len(deduped)
        filtered = filter_by_intent(deduped, intent)
        analyzed = analyze_deals(filtered)
        final = analyzed[:10]
        stats = SearchStats(
            total_found=len(all_results), total_verified=len(analyzed),
            sources_used=sorted(set(sources_used)), sources_failed=sorted(set(sources_failed)),
            duration_seconds=round(time.time() - start, 2), queries_run=q_count,
            results_filtered=before_filter - len(filtered),
        )
        return final, stats, intent

    async def _safe(self, fn, query, name, used, failed):
        try:
            res = await fn(query)
            if res: used.append(name)
            return res
        except Exception as e:
            logger.warning(f"{name} failed for '{query}': {e}")
            failed.append(name); return []

    async def format_report(self, deals: List[DealResult], stats: SearchStats, intent: SearchIntent) -> str:
        if not deals:
            return self._no_results(stats, intent)
        ai = get_ai_service()
        facts_lines = []
        for i, d in enumerate(deals[:10], 1):
            facts_lines.append(
                f"{i}. نام: {d.product_name}\n   فروشگاه: {d.store}\n"
                f"   قیمت فعلی: {d.current_price if d.current_price else 'نامشخص'} تومان\n"
                f"   قیمت قبلی: {d.listed_old_price if d.listed_old_price else 'نامشخص'} تومان\n"
                f"   تخفیف اسمی: {d.listed_discount_percent if d.listed_discount_percent else '—'}%\n"
                f"   تخفیف واقعی: {d.real_discount_percent if d.real_discount_percent else '—'}%\n"
                f"   وضعیت: {d.discount_status}\n   موجودی: {d.availability or 'نامشخص'}\n"
                f"   Deal Score: {d.deal_score}/100\n   لینک: {d.product_url}\n"
            )
        facts = "\n".join(facts_lines)
        prompt = f"""بر اساس داده‌های واقعی زیر، یک گزارش فارسی کوتاه و دقیق بنویس.
درخواست: «{intent.original_request}»
داده‌ها:
{facts}
آمار: {stats.total_found} نتیجه خام، {stats.total_verified} تأییدشده | منابع: {', '.join(stats.sources_used)} | زمان: {stats.duration_seconds}s
قوانین:
1. هرگز قیمت یا لینکی که در داده‌ها نیست نساز.
2. لینک‌ها را عیناً کپی کن.
3. اگر تخفیف واقعی نبود، بگو «سابقه کافی نبود».
4. حداکثر ۵ محصول.
5. فقط تگ‌های <b>, <i>, <code>, <a>.
"""
        try:
            reply, _ = await ai.ask(user_message=prompt, user_name="reporter", user_id=0,
                custom_system_prompt="گزارش‌نویس دقیق فارسی. فقط از داده‌های داده‌شده استفاده کن.", chat_history=[])
            return reply
        except Exception as e:
            logger.warning(f"Report AI failed: {e}, using fallback")
            return self._fallback_report(deals, stats, intent)

    def _fallback_report(self, deals, stats, intent) -> str:
        lines = [f"🛍️ <b>نتایج برای «{intent.original_request}»</b>",
                 f"📊 {stats.total_verified} نتیجه | {len(stats.sources_used)} منبع | ⏱ {stats.duration_seconds}s", "─"*30]
        for i, d in enumerate(deals[:6], 1):
            price = f"{d.current_price:,} تومان" if d.current_price else "نامشخص"
            disc = ""
            if d.listed_discount_percent: disc += f"اسمی: {d.listed_discount_percent}%"
            if d.real_discount_percent: disc += f" | واقعی: {d.real_discount_percent}%"
            lines.append(f"\n{i}. <b>{d.product_name}</b>\n   🏬 {d.store} | 💰 {price}\n   {disc}\n   <a href='{d.product_url}'>مشاهده</a>")
        return "\n".join(lines)

    def _no_results(self, stats, intent) -> str:
        return (f"🛍️ <b>جستجو برای «{intent.original_request}»</b>\n\n"
                f"⚠️ محصول معتبری پیدا نشد.\n"
                f"📊 {stats.queries_run} کوئری | منابع: {', '.join(stats.sources_used) or '—'}\n\n"
                f"💡 نام دقیق‌تر، برند یا درصد تخفیف را ذکر کنید.")

_engine = None
def get_engine() -> BlackHuntEngine:
    global _engine
    if _engine is None: _engine = BlackHuntEngine()
    return _engine
