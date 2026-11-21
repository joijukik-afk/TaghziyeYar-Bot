"""AutoHunter — background service that hunts 90%+ discounts automatically.

Responsibilities
----------------
1. Query every configured MCP store (Digikala / Torob / SnappShop).
2. Filter deals by minimum discount threshold (from settings).
3. Send qualified deals to every registered target group in the DB.
4. Log everything and NEVER crash the bot if a source is down.

Integration
-----------
    hunter = AutoHunter(bot)
    await hunter.start()        # background asyncio task
    ...
    await hunter.stop()

or (APScheduler):
    hunter = AutoHunter(bot)
    scheduler.add_job(hunter.run_once, "interval",
                      seconds=settings.auto_hunter_interval_seconds)
"""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime
from typing import Any, Iterable, List, Optional, Sequence

from app.config import get_settings
from app.services.blackhunt.adapters import search_all_adapters
from app.services.blackhunt.models import DealResult, HuntReport

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB helpers (defensive imports so a project layout change can't break us)
# ---------------------------------------------------------------------------

async def _load_target_groups() -> List[Any]:
    """Return every group registered as a target in the DB.

    Supports several common layouts and silently returns [] if no model is
    found, so AutoHunter keeps working (with a warning) instead of crashing.
    """
    # Try the common project layouts one by one.
    candidates: Sequence[tuple[str, str]] = (
        ("app.database.models", "Group"),
        ("app.database.models", "TargetGroup"),
        ("app.database.models", "Chat"),
        ("app.models", "Group"),
        ("app.models.group", "Group"),
    )

    session_makers: Sequence[tuple[str, str]] = (
        ("app.database.session", "async_session_maker"),
        ("app.database.session", "async_session"),
        ("app.database.session", "SessionLocal"),
        ("app.database.session", "get_session"),
        ("app.database", "async_session_maker"),
    )

    model = None
    for module_name, attr in candidates:
        try:
            module = __import__(module_name, fromlist=[attr])
            model = getattr(module, attr, None)
            if model is not None:
                break
        except Exception:
            continue

    if model is None:
        logger.warning(
            "AutoHunter: گروه‌ها در دیتابیس پیدا نشدند (مدل Group/TargetGroup موجود نیست)."
        )
        return []

    session_factory = None
    for module_name, attr in session_makers:
        try:
            module = __import__(module_name, fromlist=[attr])
            session_factory = getattr(module, attr, None)
            if session_factory is not None:
                break
        except Exception:
            continue

    if session_factory is None:
        logger.warning("AutoHunter: session factory در دیتابیس پیدا نشد.")
        return []

    try:
        # Simple call path: factory() -> async session
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
        return []
    except Exception as exc:
        logger.warning("AutoHunter: خواندن گروه‌ها از دیتابیس شکست خورد: %s", exc)
        return []


async def _select_groups(db: Any, model: Any) -> List[Any]:
    """Run SELECT * on the group model using SQLAlchemy (async or sync)."""
    try:
        from sqlalchemy import select  # local import to keep module light
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
            return [row[0] if isinstance(row, (tuple, list)) else row for row in (items or [])]
    except Exception as exc:
        logger.debug("AutoHunter select failed: %s", exc)
    return []


def _group_chat_id(group: Any) -> Optional[int]:
    """Extract a usable chat_id from whatever the ORM returns."""
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
    """Render a single deal as a Telegram-friendly HTML message."""
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

    def __init__(self, bot: Any, settings=None):
        self.bot = bot
        self.settings = settings or get_settings()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._running = False
        self._last_report: Optional[HuntReport] = None
        self._seen_urls: set[str] = set()

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        if not self.settings.auto_hunter_enabled:
            logger.info("AutoHunter is disabled via settings; not starting.")
            return
        if self._task and not self._task.done():
            logger.info("AutoHunter already running.")
            return

        self._stop_event = asyncio.Event()
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="AutoHunter")
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

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_report(self) -> Optional[HuntReport]:
        return self._last_report

    # -- main loop ----------------------------------------------------------

    async def _loop(self) -> None:
        interval = max(30, int(self.settings.auto_hunter_interval_seconds))
        # Small initial delay so the bot finishes startup cleanly.
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=5)
            return  # stopped before first run
        except asyncio.TimeoutError:
            pass

        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let the loop die
                logger.exception("AutoHunter round crashed: %s", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                continue

    # -- a single round -----------------------------------------------------

    async def run_once(self) -> HuntReport:
        """Execute one hunt round and return a summary report."""
        report = HuntReport()
        min_discount = self.settings.auto_hunter_min_discount

        # 1. load target groups
        groups = await _load_target_groups()
        report.groups_count = len(groups)
        logger.info("AutoHunter: %d گروه از دیتابیس پیدا شد", len(groups))

        if not groups:
            report.finish()
            self._last_report = report
            return report

        # 2. build the search query (you can customize this)
        query = getattr(self.settings, "auto_hunter_query", None) or "تخفیف ویژه"
        max_per_store = self.settings.auto_hunter_max_results_per_store

        # 3. fetch deals from all MCP adapters
        try:
            deals = await search_all_adapters(query, max_per_store)
        except Exception as exc:
            logger.exception("AutoHunter: search failed entirely: %s", exc)
            report.errors.append(str(exc))
            report.finish()
            self._last_report = report
            return report

        report.deals_found = len(deals)

        # 4. filter by threshold + dedupe against previous rounds
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

        # 5. broadcast
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
        """Send one message, swallowing per-group errors."""
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
        """Clear the 'already announced' cache (useful in tests)."""
        self._seen_urls.clear()


# Convenience API used by app startup
async def start_auto_hunter(bot: Any, settings=None) -> AutoHunter:
    hunter = AutoHunter(bot, settings=settings)
    await hunter.start()
    return hunter


__all__ = [
    "AutoHunter",
    "start_auto_hunter",
    "format_deal",
]
