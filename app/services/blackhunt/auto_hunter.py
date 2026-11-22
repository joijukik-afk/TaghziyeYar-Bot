"""Autonomous BlackHunt runner that publishes to Telegram groups."""
from __future__ import annotations

import asyncio
import html
import logging
from typing import Any, List, Optional

from telegram.constants import ParseMode

from app.config import get_settings
from app.services.blackhunt.analyzer import format_deal_message
from app.services.blackhunt.engine import get_engine
from app.services.blackhunt.models import HuntReport

logger = logging.getLogger(__name__)


def _fmt_price(value: int) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def format_deal(deal) -> str:
    lines = [
        f"🔥 تخفیف {deal.discount:.0f}٪",
        f"🎯 {html.escape(deal.title or 'بدون عنوان')}",
        "",
        f"⚡ قیمت: {_fmt_price(deal.price)} تومان",
    ]
    if deal.old_price and deal.old_price > deal.price:
        lines.append(
            f"❌ قیمت قبل: "
            f"<s>{_fmt_price(deal.old_price)}</s> تومان"
        )
        lines.append(
            f"💎 صرفه‌جویی: {_fmt_price(deal.savings)} تومان"
        )
    lines.append(f"🏪 فروشگاه: {deal.store}")
    lines.append("")
    lines.append(
        f'🛒 <a href="{deal.product_url}">مشاهده محصول</a>'
    )
    return "\n".join(lines)


async def _load_target_groups() -> List[Any]:
    try:
        from app.database import repository as repo
        groups = await repo.list_all_groups()
        if groups:
            logger.info(
                "AutoHunter: %d گروه از دیتابیس پیدا شد",
                len(groups),
            )
            return list(groups)
    except Exception as exc:
        logger.warning(
            "AutoHunter: failed to load groups: %s", exc
        )
    return []


def _group_chat_id(group: Any) -> Optional[int]:
    for attr in (
        "chat_id", "group_id", "tg_id",
        "telegram_id", "id",
    ):
        value = getattr(group, attr, None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


class AutoHunter:
    def __init__(self, bot: Any = None, settings=None):
        self.bot = bot
        self.settings = settings or get_settings()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._running = False
        self._last_report: Optional[HuntReport] = None
        self._seen_urls: set = set()

    async def start(self) -> None:
        if not self.settings.auto_hunter_enabled:
            logger.info(
                "AutoHunter is disabled via settings; not starting."
            )
            return
        if self._task and not self._task.done():
            logger.info("AutoHunter already running.")
            return
        self._stop_event = asyncio.Event()
        self._running = True
        self._task = asyncio.create_task(
            self.run_forever(), name="AutoHunter"
        )
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
        interval = max(
            30, int(self.settings.auto_hunter_interval_seconds)
        )
        logger.info(
            "AutoHunter started: min_discount=%s%%, interval=%ss",
            self.settings.auto_hunter_min_discount,
            interval,
        )
        # Initial 5-second warm-up so the bot startup completes
        try:
            await asyncio.wait_for(
                self._stop_event.wait(), timeout=5
            )
            return
        except asyncio.TimeoutError:
            pass

        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "AutoHunter round failed: %s", exc
                )
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=interval
                )
            except asyncio.TimeoutError:
                continue

    async def run_once(self) -> HuntReport:
        report = HuntReport()
        min_discount = self.settings.auto_hunter_min_discount

        if not self.bot:
            logger.warning(
                "AutoHunter has no bot instance; skipping round."
            )
            report.finish()
            self._last_report = report
            return report

        groups = await _load_target_groups()
        report.groups_count = len(groups)
        if not groups:
            logger.warning(
                "AutoHunter: no target groups found in DB."
            )
            report.finish()
            self._last_report = report
            return report

        query = (
            getattr(self.settings, "auto_hunter_query", None)
            or "تخفیف بلک فرایدی"
        )
        max_per_store = (
            self.settings.auto_hunter_max_results_per_store
        )

        engine = get_engine()
        try:
            ranked, stats, _ = await engine.search(
                query, max_per_source=max_per_store
            )
        except Exception as exc:
            logger.exception(
                "AutoHunter: engine.search failed: %s", exc
            )
            report.errors.append(str(exc))
            report.finish()
            self._last_report = report
            return report

        report.deals_found = stats.total_deals

        for v in ranked:
            if v.tier in ("C", "UNVERIFIED"):
                continue
            if v.real_discount < min_discount:
                continue
            fp = (
                f"{v.deal.store}:{v.deal.product_url}"
                .lower()
                .strip()
            )
            if fp in self._seen_urls:
                report.duplicates_skipped += 1
                continue

            text = format_deal_message(v)
            sent_for_deal = 0
            for group in groups:
                chat_id = _group_chat_id(group)
                if chat_id is None:
                    continue
                if await self._send(chat_id, text):
                    sent_for_deal += 1
                await asyncio.sleep(1.2)

            if sent_for_deal:
                self._seen_urls.add(fp)
                report.deals_sent += sent_for_deal
                logger.info(
                    "AutoHunter: deal '%s' (%s%%) "
                    "sent to %d group(s)",
                    v.deal.title,
                    v.real_discount,
                    sent_for_deal,
                )

        report.finish()
        self._last_report = report
        logger.info(
            "AutoHunter round done in %.1fs — "
            "found=%d qualified=%d sent=%d",
            report.duration_seconds,
            report.deals_found,
            report.deals_qualified,
            report.deals_sent,
        )
        return report

    async def _send(self, chat_id: int, text: str) -> bool:
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False,
            )
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "AutoHunter: send to %s failed: %s",
                chat_id,
                exc,
            )
            return False


_auto_hunter_singleton: Optional[AutoHunter] = None


def get_auto_hunter(bot: Any = None, settings=None) -> AutoHunter:
    global _auto_hunter_singleton
    if _auto_hunter_singleton is None:
        _auto_hunter_singleton = AutoHunter(
            bot=bot, settings=settings
        )
    elif bot is not None:
        _auto_hunter_singleton.bot = bot
    return _auto_hunter_singleton


async def start_auto_hunter(
    bot: Any, settings=None,
) -> AutoHunter:
    hunter = get_auto_hunter(bot=bot, settings=settings)
    await hunter.start()
    return hunter


__all__ = [
    "AutoHunter",
    "start_auto_hunter",
    "get_auto_hunter",
    "format_deal",
]
