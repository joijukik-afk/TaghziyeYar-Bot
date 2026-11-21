"""برنامه‌ریز کوئری — AI فقط فیلترها و کوئری‌ها را می‌سازد."""
import json, logging, re
from app.services.ai_service import get_ai_service
from app.services.blackhunt.models import SearchIntent

logger = logging.getLogger(__name__)

PLANNER_SYSTEM = """You are a Persian search query planner for an Iranian shopping search engine.
Given a user request in Persian, output ONLY a valid JSON object (no markdown):
{
  "intent_type": "specific_product" | "general_deals" | "category_browse",
  "queries": ["3-5 Persian and English search queries"],
  "category": "mobile|laptop|gaming|clothing|beauty|home|supplement|food|other|null",
  "brands": ["detected brand names"],
  "min_discount": null or integer 1-100,
  "price_min": null or integer (Toman),
  "price_max": null or integer (Toman),
  "must_be_in_stock": true/false
}
Rules:
- general_deals → user asks for generic discounts ("چه چیزهایی تخفیف خورده", "بالای ۹۰ درصد")
- specific_product → user names a specific product ("کراتین", "آیفون ۱۵")
- Always include English synonyms in queries
- If user mentions "۹۰ درصد" → set min_discount=90
- NEVER invent product names. ONLY output search queries.
"""

async def plan_search(user_request: str) -> SearchIntent:
    ai = get_ai_service()
    try:
        reply, _ = await ai.ask(
            user_message=f"درخواست کاربر: {user_request}",
            user_name="planner", user_id=0,
            custom_system_prompt=PLANNER_SYSTEM, chat_history=[],
        )
        json_match = re.search(r"\{.*\}", reply or "", re.DOTALL)
        if not json_match:
            raise ValueError("no json in reply")
        data = json.loads(json_match.group(0))
        queries = [q for q in data.get("queries", []) if q and isinstance(q, str)]
        if not queries:
            queries = [user_request]
        return SearchIntent(
            intent_type=data.get("intent_type", "specific_product"),
            queries=queries[:5], category=data.get("category"),
            brands=data.get("brands", []) or [], min_discount=data.get("min_discount"),
            price_min=data.get("price_min"), price_max=data.get("price_max"),
            must_be_in_stock=data.get("must_be_in_stock", True),
            original_request=user_request,
        )
    except Exception as e:
        logger.warning(f"Planner failed: {e}, using fallback")
        return SearchIntent(intent_type="specific_product", queries=[user_request], original_request=user_request)
