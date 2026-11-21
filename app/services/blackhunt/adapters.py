"""Data adapters for BlackHunt / AutoHunter.

Sources:
    - MCP servers for Digikala, Torob and SnappShop.
    - Optional Tavily web fallback (only when TAVILY_API_KEY is configured).

Handles both plain JSON and SSE (text/event-stream) MCP responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Iterable, List, Optional

import httpx

from app.config import get_settings
from app.services.blackhunt.models import DealResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_NUM_TRANS = str.maketrans(PERSIAN_DIGITS + ARABIC_DIGITS, "0123456789" * 2)

STORE_URL_PATTERNS = {
    "digikala": re.compile(r"^https?://(?:www\.)?digikala\.com/product/dkp-\d+", re.I),
    "torob": re.compile(r"^https?://(?:www\.)?torob\.com/p/[A-Za-z0-9]+", re.I),
    "snappshop": re.compile(r"^https?://(?:www\.)?snappshop\.ir/product/\d+", re.I),
}

STORE_DOMAINS = {
    "digikala": "digikala.com",
    "torob": "torob.com",
    "snappshop": "snappshop.ir",
}

GENERIC_PRODUCT_HINTS = (
    "/product/", "/products/", "/p/", "/dp/", "/dkp-", "/item/", "/goods/", "/pdp/",
)
FAKE_ID_HINTS = ("1234567", "123456", "000000", "111111", "999999")

PRICE_PATTERNS = (
    r"([۰-۹]{1,3}(?:[,،.][۰-۹]{3})+)",
    r"([٠-٩]{1,3}(?:[,،.][٠-٩]{3})+)",
    r"([0-9]{1,3}(?:[,،.][0-9]{3})+)",
    r"([0-9]{5,9})",
)

MIN_PRICE = 10_000
MAX_PRICE = 500_000_000


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def normalize_numbers(text: str) -> str:
    if not text:
        return ""
    text = str(text).translate(_NUM_TRANS)
    return re.sub(r"[,،\s]", "", text)


def extract_prices(text: str) -> List[int]:
    if not text:
        return []
    found: List[int] = []
    for pattern in PRICE_PATTERNS:
        for raw in re.findall(pattern, str(text)):
            clean = normalize_numbers(raw)
            if not clean.isdigit():
                continue
            try:
                value = int(clean)
            except ValueError:
                continue
            if MIN_PRICE < value < MAX_PRICE:
                found.append(value)
    return sorted(set(found))


def store_from_url(url: str) -> str:
    if not url:
        return "unknown"
    lowered = url.lower()
    for store, domain in STORE_DOMAINS.items():
        if domain in lowered:
            return store
    try:
        host = url.split("//", 1)[1].split("/", 1)[0]
        return host.replace("www.", "").split(".")[0]
    except Exception:
        return "unknown"


def is_valid_product_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    if any(fake in url for fake in FAKE_ID_HINTS):
        return False

    lowered = url.lower()
    for store, pattern in STORE_URL_PATTERNS.items():
        if STORE_DOMAINS[store] in lowered:
            return bool(pattern.match(url))

    return any(hint in lowered for hint in GENERIC_PRODUCT_HINTS)


def _compute_discount(price: int, old_price: int, listed: float) -> float:
    try:
        if old_price and price and old_price > price:
            return round((old_price - price) / old_price * 100, 1)
    except Exception:
        pass
    try:
        return float(listed or 0)
    except Exception:
        return 0.0


def _coerce_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        digits = normalize_numbers(value)
        if digits.isdigit():
            try:
                return int(digits)
            except ValueError:
                return 0
    return 0


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


# ---------------------------------------------------------------------------
# 🆕 MCP response parser (handles JSON + SSE)
# ---------------------------------------------------------------------------

def _parse_mcp_response(resp: httpx.Response) -> Any:
    """
    Parse an MCP response that may be:
      - plain JSON (application/json)
      - SSE stream (text/event-stream), where each event has `data: {json}`

    Returns the parsed Python object, or None if parsing fails.
    """
    content_type = (resp.headers.get("content-type") or "").lower()

    # --- SSE branch ---
    if "text/event-stream" in content_type:
        events_data: List[str] = []
        current: List[str] = []

        for line in resp.text.splitlines():
            if line.startswith("data:"):
                current.append(line[5:].lstrip())
            elif line.strip() == "":
                if current:
                    events_data.append("\n".join(current))
                    current = []
        if current:
            events_data.append("\n".join(current))

        last_valid: Any = None
        for block in events_data:
            if not block:
                continue
            try:
                parsed = json.loads(block)
            except json.JSONDecodeError:
                continue
            last_valid = parsed
            # Prefer a payload that actually contains a result/error.
            if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
                return parsed

        return last_valid

    # --- Plain JSON branch ---
    if not resp.content:
        return None
    try:
        return resp.json()
    except json.JSONDecodeError:
        # Some servers return JSON with a wrong content-type; try text fallback.
        try:
            return json.loads(resp.text)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# MCP Adapter
# ---------------------------------------------------------------------------

class MCPAdapter:
    """One MCP server (Digikala / Torob / SnappShop)."""

    def __init__(self, name: str, endpoint: str, settings=None):
        self.settings = settings or get_settings()
        self.name = name
        self.endpoint = endpoint
        self._session_id: Optional[str] = None
        self._tool_name: Optional[str] = None
        self._initialized: bool = False
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(
                self.settings.mcp_timeout_seconds,
                connect=self.settings.mcp_connect_timeout_seconds,
            ),
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            follow_redirects=True,
        )

    # -- lifecycle ----------------------------------------------------------

    async def close(self) -> None:
        try:
            await self._http.aclose()
        except Exception:
            pass

    aclose = close

    async def __aenter__(self) -> "MCPAdapter":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # -- MCP handshake ------------------------------------------------------

    def _session_headers(self) -> dict:
        return {"Mcp-Session-Id": self._session_id} if self._session_id else {}

    async def _initialize(self) -> bool:
        """Best-effort MCP initialize. Returns True if the server responded."""
        if self._initialized:
            return True

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TaghziyeYar-Bot", "version": "1.0"},
            },
        }
        try:
            resp = await self._http.post(self.endpoint, json=payload)
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            logger.debug(f"MCP {self.name} initialize failed: {exc}")
            return False

        if resp.status_code >= 500:
            logger.debug(f"MCP {self.name} initialize returned {resp.status_code}")
            return False

        if resp.status_code >= 400:
            logger.warning(
                f"MCP {self.name} initialize HTTP {resp.status_code}: "
                f"{resp.text[:150]}"
            )
            return False

        self._session_id = (
            resp.headers.get("Mcp-Session-Id")
            or resp.headers.get("mcp-session-id")
        )

        # Parse response body (SSE or JSON) — not strictly needed, but validates.
        parsed = _parse_mcp_response(resp)
        if parsed is None:
            logger.debug(f"MCP {self.name} initialize: unparsable body (ignored)")

        # Send the "initialized" notification (some servers require it).
        try:
            await self._http.post(
                self.endpoint,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=self._session_headers(),
            )
        except Exception:
            pass

        self._initialized = True
        return True

    async def _discover_tool(self) -> Optional[str]:
        """Find a sensible 'search' tool on the server."""
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
        try:
            resp = await self._http.post(
                self.endpoint, json=payload, headers=self._session_headers()
            )
            resp.raise_for_status()
            data = _parse_mcp_response(resp)
        except Exception as exc:
            logger.debug(f"MCP {self.name} tools/list failed: {exc}")
            return None

        if not isinstance(data, dict):
            return None

        tools = (data.get("result") or {}).get("tools") or []
        if not tools:
            return None

        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = (tool.get("name") or "").lower()
            if any(kw in name for kw in ("search", "query", "find", "product")):
                return tool.get("name")
        return tools[0].get("name") if isinstance(tools[0], dict) else None

    async def _ensure_ready(self) -> bool:
        if self._tool_name:
            return True

        ok = await self._initialize()
        if not ok:
            return False

        self._tool_name = await self._discover_tool() or "search"
        return True

    # -- public search ------------------------------------------------------

    async def search(self, query: str, max_results: Optional[int] = None) -> List[DealResult]:
        max_results = max_results or self.settings.auto_hunter_max_results_per_store

        try:
            if not await self._ensure_ready():
                logger.warning(
                    "MCP %s is unreachable (%s). Skipping this source.",
                    self.name, self.endpoint,
                )
                return []

            raw = await self._call_search_tool(query, max_results)
            return self._parse_deals(raw, max_results)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "MCP %s HTTP %s: %s",
                self.name, exc.response.status_code, exc.response.text[:200],
            )
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            logger.warning("MCP %s connection error: %s", self.name, exc)
        except Exception as exc:
            logger.warning("MCP %s unexpected error: %s", self.name, exc, exc_info=True)
        return []

    # -- internals ----------------------------------------------------------

    async def _call_search_tool(self, query: str, max_results: int) -> Any:
        assert self._tool_name is not None
        arguments_variants = [
            {"query": query, "limit": max_results},
            {"query": query, "top_k": max_results},
            {"query": query, "max_results": max_results},
            {"query": query},
            {"q": query, "limit": max_results},
        ]

        last_error: Optional[Exception] = None
        for arguments in arguments_variants:
            payload = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": self._tool_name, "arguments": arguments},
            }
            try:
                resp = await self._http.post(
                    self.endpoint, json=payload, headers=self._session_headers()
                )
                resp.raise_for_status()

                # ✅ FIX: use the SSE-aware parser instead of resp.json()
                parsed = _parse_mcp_response(resp)
                if parsed is None:
                    # Empty or unparsable — treat as no result.
                    return {}
                return parsed
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code in (400, 422):
                    continue
                raise
            except Exception as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        return {}

    # -- response parsing ---------------------------------------------------

    def _parse_deals(self, payload: Any, max_results: int) -> List[DealResult]:
        items = self._extract_items(payload)
        results: List[DealResult] = []

        for item in items:
            if not isinstance(item, dict):
                continue
            deal = self._to_deal(item)
            if deal is not None:
                results.append(deal)
            if len(results) >= max_results:
                break

        return results

    def _extract_items(self, payload: Any) -> List[Any]:
        if payload is None:
            return []
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []

        result = payload.get("result") or payload
        if isinstance(result, list):
            return result
        if not isinstance(result, dict):
            return []

        content = result.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parsed = _try_json(block["text"])
                    found = self._extract_items(parsed)
                    if found:
                        return found
                elif isinstance(block, dict) and block.get("url"):
                    return content

        for key in ("structuredContent", "items", "results", "products", "data", "deals"):
            candidate = result.get(key)
            if isinstance(candidate, list):
                return candidate
            if isinstance(candidate, dict):
                for nested_key in ("items", "results", "products", "data"):
                    nested = candidate.get(nested_key)
                    if isinstance(nested, list):
                        return nested

        return []

    def _to_deal(self, item: dict) -> Optional[DealResult]:
        url = _first(
            item.get("product_url"), item.get("url"), item.get("link"),
            item.get("permalink"), item.get("href"),
        )
        if not url or not isinstance(url, str) or not is_valid_product_url(url):
            return None

        title = (
            _first(
                item.get("title"), item.get("name"), item.get("product_name"),
                item.get("productName"),
            )
            or "بدون عنوان"
        )

        price = _coerce_int(_first(
            item.get("price"), item.get("current_price"),
            item.get("selling_price"), item.get("final_price"),
        ))
        old_price = _coerce_int(_first(
            item.get("old_price"), item.get("original_price"),
            item.get("regular_price"), item.get("list_price"),
        ))

        if not price:
            prices = extract_prices(_first(
                item.get("price_text"), item.get("priceText"), title,
            ) or "")
            if prices:
                price = prices[0]
                if not old_price and len(prices) > 1:
                    old_price = prices[-1]

        listed_discount = float(_first(
            item.get("discount_percent"), item.get("discount"),
            item.get("discountPercent"), item.get("off"), 0,
        ) or 0)
        real_discount = _compute_discount(price, old_price, listed_discount)

        return DealResult(
            title=str(title).strip(),
            product_url=url,
            store=store_from_url(url),
            price=price,
            old_price=old_price,
            listed_discount_percent=listed_discount,
            real_discount_percent=real_discount,
            source=self.name,
        )


def _try_json(text: str) -> Any:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Tavily fallback (optional)
# ---------------------------------------------------------------------------

class TavilyAdapter:
    """Web-search fallback. Only used when TAVILY_API_KEY is configured."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.name = "tavily"

    async def search(self, query: str, max_results: int) -> List[DealResult]:
        try:
            from tavily import TavilyClient  # type: ignore
        except ImportError:
            logger.warning("tavily-python is not installed; skipping Tavily fallback.")
            return []

        def _sync_call() -> Any:
            client = TavilyClient(api_key=self.api_key)
            return client.search(
                query=query,
                max_results=max_results,
                include_domains=list(STORE_DOMAINS.values()),
                search_depth="basic",
            )

        try:
            data = await asyncio.to_thread(_sync_call)
        except Exception as exc:
            logger.warning("Tavily search failed: %s", exc)
            return []

        results: List[DealResult] = []
        for item in (data or {}).get("results", []):
            url = item.get("url") or ""
            if not is_valid_product_url(url):
                continue
            prices = extract_prices(item.get("content") or "")
            price = prices[0] if prices else 0
            old_price = prices[-1] if len(prices) > 1 else 0
            results.append(
                DealResult(
                    title=item.get("title") or "بدون عنوان",
                    product_url=url,
                    store=store_from_url(url),
                    price=price,
                    old_price=old_price,
                    listed_discount_percent=0.0,
                    real_discount_percent=_compute_discount(price, old_price, 0),
                    source=self.name,
                )
            )
        return results[:max_results]


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def build_adapters(settings=None) -> List[MCPAdapter]:
    settings = settings or get_settings()
    adapters: List[MCPAdapter] = []
    for store in settings.enabled_mcp_stores:
        try:
            endpoint = settings.mcp_endpoint_for(store)
        except Exception as exc:
            logger.warning("Cannot resolve MCP endpoint for %s: %s", store, exc)
            continue
        if not endpoint:
            continue
        adapters.append(MCPAdapter(store, endpoint, settings=settings))
    return adapters


async def search_all_adapters(
    query: str,
    max_results: Optional[int] = None,
    use_tavily_fallback: bool = True,
) -> List[DealResult]:
    settings = get_settings()
    per_store = max_results or settings.auto_hunter_max_results_per_store

    adapters = build_adapters(settings)
    tasks = [adapter.search(query, per_store) for adapter in adapters]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    deals: List[DealResult] = []
    for adapter, outcome in zip(adapters, raw_results):
        if isinstance(outcome, Exception):
            logger.warning("MCP %s failed: %s", adapter.name, outcome)
            continue
        deals.extend(outcome or [])

    for adapter in adapters:
        await adapter.close()

    if not deals and use_tavily_fallback and settings.tavily_api_key:
        tavily = TavilyAdapter(settings.tavily_api_key)
        deals = await tavily.search(query, per_store)

    return _dedupe_deals(deals)


async def close_adapters(adapters: Iterable[MCPAdapter]) -> None:
    await asyncio.gather(*(a.close() for a in adapters), return_exceptions=True)


def _dedupe_deals(deals: Iterable[DealResult]) -> List[DealResult]:
    seen: set[str] = set()
    unique: List[DealResult] = []
    for deal in deals:
        url = getattr(deal, "product_url", None)
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(deal)
    return unique


__all__ = [
    "MCPAdapter",
    "TavilyAdapter",
    "build_adapters",
    "search_all_adapters",
    "close_adapters",
    "is_valid_product_url",
    "store_from_url",
    "extract_prices",
    "normalize_numbers",
]
