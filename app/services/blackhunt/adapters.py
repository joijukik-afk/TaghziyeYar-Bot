"""Real Iranian shopping adapters — Digikala, Torob, SnappShop."""
from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from typing import List, Optional
from urllib.parse import quote_plus

import httpx

from app.services.blackhunt.models import DealResult

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

ALLOWED_DOMAINS = {
    "digikala.com", "www.digikala.com",
    "torob.com", "www.torob.com",
    "snappshop.ir", "snapp.market",
}


def is_valid_product_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        return host in ALLOWED_DOMAINS
    except Exception:
        return False


def extract_prices(text: str) -> List[int]:
    if not text:
        return []
    patterns = (
        r"([۰-۹]{1,3}(?:[,،.][۰-۹]{3})+)",
        r"([0-9]{1,3}(?:[,،.][0-9]{3})+)",
        r"([0-9]{5,9})",
    )
    found: List[int] = []
    for p in patterns:
        for m in re.findall(p, str(text)):
            clean = (
                m.replace(",", "")
                .replace("،", "")
                .replace(".", "")
            )
            clean = clean.translate(
                str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
            )
            try:
                v = int(clean)
                if 10_000 < v < 500_000_000:
                    found.append(v)
            except ValueError:
                pass
    return sorted(set(found))


def normalize_numbers(text: str) -> str:
    if not text:
        return ""
    text = str(text).translate(
        str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
            "01234567890123456789",
        )
    )
    return re.sub(r"[,،\s]", "", text)


def store_from_url(url: str) -> str:
    if not url:
        return "unknown"
    for domain, name in (
        ("digikala.com", "دیجی‌کالا"),
        ("torob.com", "ترب"),
        ("snappshop.ir", "اسنپ‌شاپ"),
        ("snapp.market", "اسنپ‌شاپ"),
    ):
        if domain in url.lower():
            return name
    return "فروشگاه"


class BaseAdapter(ABC):
    name: str = "base"
    timeout: float = 20.0

    def __init__(self) -> None:
        self.last_error: Optional[str] = None

    @abstractmethod
    async def search(
        self, query: str, max_results: int = 10
    ) -> List[DealResult]:
        ...


class DigikalaAdapter(BaseAdapter):
    name = "digikala"
    API = "https://api.digikala.com/v1/search/?q={q}&page=1"

    async def search(
        self, query: str, max_results: int = 10
    ) -> List[DealResult]:
        out: List[DealResult] = []
        url = self.API.format(q=quote_plus(query))
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers={"User-Agent": UA})
            if resp.status_code != 200:
                self.last_error = f"status={resp.status_code}"
                return out
            data = resp.json()
            products = (data.get("data") or {}).get("products") or []
            for item in products[:max_results]:
                price_info = item.get("price") or {}
                selling = price_info.get("selling_price") or 0
                if selling <= 0:
                    continue
                rrp = price_info.get("rrp_price") or 0
                dkp = item.get("id")
                deal = DealResult(
                    title=(item.get("title_fa") or "").strip()[:180],
                    product_url=(
                        f"https://www.digikala.com/product/dkp-{dkp}/"
                    ),
                    store="دیجی‌کالا",
                    price=int(selling) // 10,
                    old_price=int(rrp) // 10 if rrp else 0,
                    listed_discount_percent=float(
                        price_info.get("discount_percent") or 0
                    ),
                    source=self.name,
                    image_url=(
                        (item.get("images") or {}).get("main") or {}
                    ).get("url_absolute"),
                    availability=(
                        "موجود"
                        if item.get("status") == "marketable"
                        else "ناموجود"
                    ),
                )
                if is_valid_product_url(deal.product_url):
                    out.append(deal)
        except Exception as exc:
            self.last_error = str(exc)
            logger.error("[digikala] failed: %s", exc)
        return out


class TorobAdapter(BaseAdapter):
    name = "torob"
    API = (
        "https://api.torob.com/v4/base-product/search/"
        "?page=0&size=24&query={q}"
    )

    async def search(
        self, query: str, max_results: int = 10
    ) -> List[DealResult]:
        out: List[DealResult] = []
        url = self.API.format(q=quote_plus(query))
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers={"User-Agent": UA})
            if resp.status_code != 200:
                self.last_error = f"status={resp.status_code}"
                return out
            data = resp.json()
            results = data.get("results") or []
            for item in results[:max_results]:
                price = item.get("price") or 0
                if not price:
                    continue
                prk = item.get("random_key") or item.get("prk")
                if not prk:
                    continue
                deal = DealResult(
                    title=(
                        item.get("name1") or item.get("name2") or ""
                    ).strip()[:180],
                    product_url=f"https://torob.com/p/{prk}/",
                    store="ترب",
                    price=int(price) // 10,
                    old_price=int(item.get("old_price") or 0) // 10,
                    source=self.name,
                    image_url=item.get("image_url"),
                    availability=(
                        "موجود"
                        if item.get("availability")
                        else "نامشخص"
                    ),
                )
                if is_valid_product_url(deal.product_url):
                    out.append(deal)
        except Exception as exc:
            self.last_error = str(exc)
            logger.error("[torob] failed: %s", exc)
        return out


class SnappShopAdapter(BaseAdapter):
    name = "snappshop"
    API = (
        "https://apix.snappshop.ir/api/v1/products/search"
        "?query={q}&size=20"
    )

    async def search(
        self, query: str, max_results: int = 10
    ) -> List[DealResult]:
        out: List[DealResult] = []
        url = self.API.format(q=quote_plus(query))
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers={"User-Agent": UA})
            if resp.status_code != 200:
                self.last_error = f"status={resp.status_code}"
                return out
            data = resp.json()
            items = data.get("data") or data.get("products") or []
            for item in items[:max_results]:
                price = (
                    item.get("price")
                    or item.get("final_price")
                    or 0
                )
                if not price:
                    continue
                pid = item.get("id") or item.get("product_id")
                if not pid:
                    continue
                deal = DealResult(
                    title=(
                        item.get("title") or item.get("name") or ""
                    ).strip()[:180],
                    product_url=f"https://snapp.market/product/{pid}",
                    store="اسنپ‌شاپ",
                    price=int(price) // 10,
                    old_price=int(item.get("old_price") or 0) // 10,
                    source=self.name,
                    image_url=item.get("image"),
                    availability=(
                        "موجود"
                        if item.get("is_available", True)
                        else "ناموجود"
                    ),
                )
                if is_valid_product_url(deal.product_url):
                    out.append(deal)
        except Exception as exc:
            self.last_error = str(exc)
            logger.error("[snappshop] failed: %s", exc)
        return out


class MCPAdapter(BaseAdapter):
    """Deprecated stub kept for backward compatibility."""

    name = "mcp_disabled"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__()
        self.last_error = "MCPAdapter is deprecated"

    async def search(
        self, query: str, max_results: int = 10
    ) -> List[DealResult]:
        logger.warning(
            "MCPAdapter is deprecated; use dedicated adapters instead."
        )
        return []


ADAPTER_CLASSES = {
    "digikala": DigikalaAdapter,
    "torob": TorobAdapter,
    "snappshop": SnappShopAdapter,
}


def build_adapters(
    enabled: Optional[List[str]] = None,
) -> List[BaseAdapter]:
    keys = enabled or list(ADAPTER_CLASSES.keys())
    return [
        ADAPTER_CLASSES[k]() for k in keys if k in ADAPTER_CLASSES
    ]


async def search_all_adapters(
    query: str, max_results: int = 10,
) -> List[DealResult]:
    adapters = build_adapters()
    tasks = [
        a.search(query, max_results=max_results) for a in adapters
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    merged: List[DealResult] = []
    for adapter, res in zip(adapters, results):
        if isinstance(res, Exception):
            logger.warning(
                "[%s] adapter failed: %s", adapter.name, res
            )
            continue
        merged.extend(res)
    return merged


async def close_adapters() -> None:
    return None
