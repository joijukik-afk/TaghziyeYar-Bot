"""آداپترهای داده — MCP Servers + Tavily Web Search. فقط داده‌های واقعی."""
import logging, asyncio, re
from typing import List, Optional
from urllib.parse import quote_plus
import httpx
from tavily import TavilyClient
from app.services.blackhunt.models import DealResult
from app.config import get_settings

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

# 👈 آدرس‌های واقعی MCP (نمونه - باید جایگزین شود)
MCP_ENDPOINTS = {
    "digikala": "http://localhost:8000/mcp",  # digikala-mcp
    "torob": "http://localhost:8001/mcp",      # torob-mcp
    "snappshop": "http://localhost:8002/mcp", # snappshop-mcp
}

URL_PATTERNS = {
    "digikala.com": r"^https?://(?:www\.)?digikala\.com/product/dkp-\d+",
    "torob.com": r"^https?://(?:www\.)?torob\.com/p/[a-zA-Z0-9]+",
    "snappshop.ir": r"^https?://(?:www\.)?snappshop\.ir/product/\d+",
}

def is_valid_product_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")): return False
    if any(fid in url for fid in ("1234567", "123456", "000000", "111111")): return False
    for domain, pattern in URL_PATTERNS.items():
        if domain in url: return bool(re.match(pattern, url, re.IGNORECASE))
    return any(p in url.lower() for p in ("/product/", "/p/", "/dp/", "/dkp-", "/item/"))

def store_from_url(url: str) -> str:
    for store, domain in (("digikala","digikala.com"),("torob","torob.com"),("snappshop","snappshop.ir")):
        if domain in url: return store
    try: return url.split("//")[1].split("/")[0].replace("www.","").split(".")[0]
    except: return "unknown"

def _extract_prices(text: str) -> List[int]:
    if not text: return []
    patterns = (r"([۰-۹]{1,3}(?:[,،.][۰-۹]{3})+)", r"([0-9]{1,3}(?:[,،.][0-9]{3})+)", r"([0-9]{5,9})")
    found = []
    for p in patterns:
        for m in re.findall(p, text):
            clean = m.replace(",","").replace("،","").replace(".","").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹","0123456789"))
            try:
                v = int(clean)
                if 10_000 < v < 500_000_000: found.append(v)
            except: pass
    return sorted(set(found))

class MCPAdapter:
    """آداپتر عمومی برای اتصال به سرورهای MCP."""
    def __init__(self, name: str, endpoint: str):
        self.name = name
        self.endpoint = endpoint
        self._http = httpx.AsyncClient(timeout=20.0, headers={"User-Agent": UA})

    async def close(self): await self._http.aclose()

    async def search(self, query: str, max_results: int = 6) -> List[DealResult]:
        results: List[DealResult] = []
        try:
            # فرض بر این است که MCP از JSON-RPC پشتیبانی می‌کند
            payload = {
                "jsonrpc": "2.0", "method": "tools/call",
                "params": {"name": "search_products", "arguments": {"query": query, "limit": max_results}},
                "id": 1
            }
            resp = await self._http.post(self.endpoint, json=payload)
            if resp.status_code != 200:
                logger.warning(f"MCP {self.name} returned {resp.status_code}")
                return results
            data = resp.json().get("result", {}).get("data", [])
            for item in data:
                url = item.get("url", "")
                if not is_valid_product_url(url): continue
                price = item.get("price")
                old_price = item.get("old_price")
                disc = round((1 - price/old_price)*100) if price and old_price and old_price > price else None
                results.append(DealResult(
                    product_name=item.get("title", "")[:150], store=self.name,
                    product_url=url, current_price=price, listed_old_price=old_price,
                    listed_discount_percent=disc, availability=item.get("availability", "unknown"),
                    source_provider=f"mcp_{self.name}",
                ))
        except Exception as e:
            logger.warning(f"MCP {self.name} search failed: {e}")
        return results

class TavilyWebAdapter:
    name = "tavily"
    def __init__(self):
        key = get_settings().tavily_api_key
        self.client = TavilyClient(api_key=key) if key else None

    async def search(self, query: str, max_results: int = 6) -> List[DealResult]:
        if not self.client: return []
        results: List[DealResult] = []
        try:
            full_query = f"{query} خرید قیمت تخفیف بلک فرایدی سایت فروشگاهی ایران"
            res = await asyncio.to_thread(self.client.search, query=full_query, search_depth="advanced", max_results=8)
            for item in res.get("results", []):
                url = item.get("url", "")
                if not is_valid_product_url(url): continue
                content = item.get("content", "")
                prices = _extract_prices(content)
                current = min(prices) if prices else None
                old = max(prices) if len(prices) > 1 else None
                disc = round((1 - current/old)*100) if old and current and old > current else None
                results.append(DealResult(
                    product_name=(item.get("title") or "")[:150], store=store_from_url(url),
                    product_url=url, current_price=current, listed_old_price=old,
                    listed_discount_percent=disc, availability="unknown", source_provider="tavily",
                ))
        except Exception as e:
            logger.warning(f"Tavily search failed: {e}")
        return results
