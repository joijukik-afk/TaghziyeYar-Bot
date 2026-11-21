"""AutoHunter — background service that hunts 90%+ discounts automatically.

Responsibilities
----------------
1. Query every configured MCP store (Digikala / Torob / SnappShop).
2. Filter deals by minimum discount threshold (from settings).
3. Send qualified deals to every registered target group in the DB.
4. Log everything and NEVER crash the bot if a source is down.

Usage in main.py
----------------
    from app.services.blackhunt import get_auto_hunter

    hunter = get_auto_hunter(application.bot)
    task   = asyncio.create_task(hunter.run_forever(), name="AutoHunter")
    ...
    task.cancel()
"""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime
from typing import Any, List, Optional, Sequence

from app.config import get_settings
from app.services.blackhunt.adapters import search_all_adapters
from app.services.blackhunt.models import DealResult, HuntReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers (defensive: work even if project layout changes)
# ---------------------------------------------------------------------------

async def _load_target_groups() -> List[Any]:
    """Return every group registered as a target in the DB."""
    model_candidates: Sequence[tuple[str, str]] = (
        ("app.database.models", "Group"),
        ("app.database.models", "TargetGroup"),
        ("app.database.models", "Chat"),
        ("app.database.group_models", "Group"),
        ("app.models", "Group"),
        ("app.models.group", "Group"),
    )
    session_candidates: Sequence[tuple[str, str]] = (
        ("app.database.session", "async_session_maker"),
        ("app.database.session", "async_session"),
        ("app.database.session", "SessionLocal"),
        ("app.database.session", "get_session"),
        ("app.database", "async_session_maker"),
    )

    model = None
    for module_name, attr in model_candidates:
        try:
            module = __import__(module_name, fromlist=[attr])
            model = getattr(module, attr, None)
            if model is not None:
                break
        except Exception:
            continue

    if model is None:
        logger.warning("AutoHunter: no Group/TargetGroup model found in DB layer.")
        return []

    session_factory = None
    for module_name, attr in session_candidates:
        try:
            module = __import__(module_name, fromlist=[attr])
            session_factory = getattr(module, attr, None)
            if session_factory is not None:
                break
        except Exception:
            continue

    if session_factory is None:
        logger.warning("AutoHunter: no session factory found in DB layer.")
        return []

    try:
        session = session_factory()
        if hasattr(session, "__aenter__"):
            async with session as db:
                return await _select_groups(db, model)
        try:
            return await _select_groups(session, model)
        finally:
            closer = getattr(session, "close", None)
            if closer:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result
    except Exception as exc:
        logger.warning("AutoHunter: failed to read groups from DB: %s", exc)
        return []
    return []


async def _select_groups(db: Any, model: Any) -> List[Any]:
    try:
        from sqlalchemy import select
    except Exception:
        return []

    try:
        stmt = select(model)
        result = db.execute(stmt)
        if asyncio.iscoroutine(result):
            result = await result

        scalars = getattr(result, "scalars", None)
        if scalars:
            scalars = scalars()
            if asyncio.iscoroutine(scalars):
                scalars = await scalars
            all_method = getattr(scalars, "all", None)
            if all_method:
                items = all_method()
                if asyncio.iscoroutine(items):
                    items = await items
                return list(items or [])

        rows = getattr(result, "all", None)
        if rows:
            items = rows()
            if asyncio.iscoroutine(items):
                items = await items
            return [r[0] if isinstance(r, (tuple, list)) else r for r in (items or [])]
    except Exception as exc:
        logger.debug("AutoHunter select failed: %s", exc)
    return []


def _group_chat_id(group: Any) -> Optional[int]:
    for attr in ("chat_id", "group_id", "tg_id", "telegram_id", "id"):
        value = getattr(group, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    if isinstance(group, dict):
        for key in ("chat_id", "group_id", "tg_id", "telegram_id", "id"):
            if key in group:
                try:
                    return int(group[key])
                except (TypeError, ValueError):
                    continue
    return None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _fmt_price(value: int) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def format_deal(deal: DealResult) -> str:
    lines = [
        f"🔥 <b>تخفیف {deal.discount:.0f}٪</b>",
        f"🛍 <b>{html.escape(deal.title or 'بدون عنوان')}</b>",
        "",
        f"💵 قیمت: <b>{_fmt_price(deal.price)}</b> تومان",
    ]
    if deal.old_price and deal.old_price > deal.price:
        lines.append(f"❌ قیمت قبل: <s>{_fmt_price(deal.old_price)}</s> تومان")
        lines.append(f"💰 صرفه‌جویی: <b>{_fmt_price(deal.savings)}</b> تومان")
    lines.append(f"🏬 فروشگاه: {deal.store}")
    lines.append("")
    lines.append(f'🔗 <a href="{html.escape(deal.product_url)}">مشاهده محصول</a>')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AutoHunter
# ---------------------------------------------------------------------------

class AutoHunter:
    """Periodic hunter that scans stores and announces deals."""

    def __init__(self, bot: Any = None, settings=None):
        self.bot = bot
        self.settings = settings or get_settings()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._running = False
        self._last_report: Optional[HuntReport] = None
        self._seen_urls: set[str] = set()

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Spawn the hunter as a background asyncio task."""
        if not self.settings.auto_hunter_enabled:
            logger.info("AutoHunter is disabled via settings; not starting.")
            return
        if self._task and not self._task.done():
            logger.info("AutoHunter already running.")
            return
        self._stop_event = asyncio.Event()
        self._running = True
        self._task = asyncio.create_task(self.run_forever(), name="AutoHunter")
        logger.info(
            "AutoHunter started: min_discount=%s%%, interval=%ss",
            self.settings.auto_hunter_min_discount,
            self.settings.auto_hunter_interval_seconds,
        )

    async def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        logger.info("AutoHunter stopped.")

    async def run_forever(self) -> None:
        """Main loop. Can be run directly (via asyncio.create_task)."""
        if not self.settings.auto_hunter_enabled:
            logger.info("AutoHunter is disabled via settings; run_forever exits.")
            return
        if not self._running:
            self._stop_event = asyncio.Event()
            self._running = True

        interval = max(30, int(self.settings.auto_hunter_interval_seconds))

        # Small delay so the bot can finish startup cleanly.
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=5)
            return
        except asyncio.TimeoutError:
            pass

        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("AutoHunter round crashed: %s", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                continue

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_report(self) -> Optional[HuntReport]:
        return self._last_report

    # -- a single round -----------------------------------------------------

    async def run_once(self) -> HuntReport:
        """Execute one hunt round and return a summary report."""
        report = HuntReport()
        min_discount = self.settings.auto_hunter_min_discount

        if not self.bot:
            logger.warning("AutoHunter has no bot instance; skipping round.")
            report.finish()
            self._last_report = report
            return report

        groups = await _load_target_groups()
        report.groups_count = len(groups)
        logger.info("AutoHunter: %d گروه از دیتابیس پیدا شد", len(groups))
        if not groups:
            report.finish()
            self._last_report = report
            return report

        query = getattr(self.settings, "auto_hunter_query", None) or "تخفیف ویژه"
        max_per_store = self.settings.auto_hunter_max_results_per_store

        try:
            deals = await search_all_adapters(query, max_per_store)
        except Exception as exc:
            logger.exception("AutoHunter: search failed entirely: %s", exc)
            report.errors.append(str(exc))
            report.finish()
            self._last_report = report
            return report

        report.deals_found = len(deals)

        qualified: List[DealResult] = []
        for deal in deals:
            if deal.product_url in self._seen_urls:
                continue
            if not deal.is_qualified(min_discount):
                continue
            qualified.append(deal)
        report.deals_qualified = len(qualified)

        if not qualified:
            logger.info(
                "AutoHunter: در این دور تخفیف %s٪+ پیدا نشد", min_discount
            )
            report.finish()
            self._last_report = report
            return report

        for deal in qualified:
            text = format_deal(deal)
            sent_for_deal = 0
            for group in groups:
                chat_id = _group_chat_id(group)
                if chat_id is None:
                    continue
                if await self._send(chat_id, text):
                    sent_for_deal += 1
            if sent_for_deal:
                self._seen_urls.add(deal.product_url)
                report.deals_sent += sent_for_deal
                logger.info(
                    "AutoHunter: deal '%s' (%s%%) sent to %d group(s)",
                    deal.title, deal.discount, sent_for_deal,
                )

        report.finish()
        self._last_report = report
        logger.info(
            "AutoHunter round done in %.1fs — found=%d qualified=%d sent=%d",
            report.duration_seconds, report.deals_found,
            report.deals_qualified, report.deals_sent,
        )
        return report

    # -- helpers ------------------------------------------------------------

    async def _send(self, chat_id: int, text: str) -> bool:
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("AutoHunter: send to %s failed: %s", chat_id, exc)
            return False

    def reset_seen(self) -> None:
        self._seen_urls.clear()


# ---------------------------------------------------------------------------
# Public helpers (what main.py / __init__.py use)
# ---------------------------------------------------------------------------

# Process-wide singleton
_auto_hunter_singleton: Optional[AutoHunter] = None


def get_auto_hunter(bot: Any = None, settings=None) -> AutoHunter:
    """Return the process-wide AutoHunter singleton.

    - First call with no bot is allowed (main.py then attaches it later).
    - Subsequent calls with a bot update the reference.
    """
    global _auto_hunter_singleton
    if _auto_hunter_singleton is None:
        _auto_hunter_singleton = AutoHunter(bot=bot, settings=settings)
    elif bot is not None:
        _auto_hunter_singleton.bot = bot
    return _auto_hunter_singleton


async def start_auto_hunter(bot: Any, settings=None) -> AutoHunter:
    """Convenience: create (or reuse) the singleton and start it."""
    hunter = get_auto_hunter(bot=bot, settings=settings)
    await hunter.start()
    return hunter


__all__ = [
    "AutoHunter",
    "start_auto_hunter",
    "get_auto_hunter",
    "format_deal",
]
