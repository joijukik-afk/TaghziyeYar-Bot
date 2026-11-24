"""Smart multi-step search wizard for TaghziyeYar."""
import html
import logging

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler, CommandHandler, ConversationHandler,
    ContextTypes, MessageHandler, filters,
)

from app.services.blackhunt.query import (
    SearchQuery, STORES, SORT_OPTIONS,
    DISCOUNT_OPTIONS, CATEGORY_PRESETS,
)
from app.services.blackhunt.engine import get_engine

logger = logging.getLogger(__name__)

STORE, DISCOUNT, SORT, TEXT = range(4)
PAGE_SIZE = 5


# ====================== Helpers ======================
def _esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def _get_q(context) -> SearchQuery:
    sq = context.user_data.get("srch_q")
    if not isinstance(sq, SearchQuery):
        sq = SearchQuery()
        context.user_data["srch_q"] = sq
    return sq


def _chunk(btns, n):
    return [btns[i:i + n] for i in range(0, len(btns), n)]


# ====================== Keyboards ======================
def _store_kb(selected: set) -> InlineKeyboardMarkup:
    btns = []
    for key, name in STORES.items():
        mark = "✅" if key in selected else "⬜️"
        btns.append(InlineKeyboardButton(
            f"{mark} {name}",
            callback_data=f"srch:store:{key}",
        ))
    btns.append(InlineKeyboardButton(
        "🌐 همه", callback_data="srch:store:all",
    ))
    rows = _chunk(btns, 2)
    rows.append([
        InlineKeyboardButton(
            "➡️ بعدی", callback_data="srch:step:discount",
        ),
        InlineKeyboardButton(
            "❌ لغو", callback_data="srch:cancel",
        ),
    ])
    return InlineKeyboardMarkup(rows)


def _discount_kb(current: float) -> InlineKeyboardMarkup:
    btns = []
    for d in DISCOUNT_OPTIONS:
        mark = "✅" if float(d) == float(current) else "⬜️"
        btns.append(InlineKeyboardButton(
            f"{mark} {d}٪",
            callback_data=f"srch:disc:{d}",
        ))
    rows = _chunk(btns, 3)
    rows.append([
        InlineKeyboardButton(
            "⬅️ قبلی", callback_data="srch:step:store",
        ),
        InlineKeyboardButton(
            "➡️ بعدی", callback_data="srch:step:sort",
        ),
    ])
    return InlineKeyboardMarkup(rows)


def _sort_kb(current: str) -> InlineKeyboardMarkup:
    btns = []
    for key, name in SORT_OPTIONS.items():
        mark = "✅" if key == current else "⬜️"
        btns.append(InlineKeyboardButton(
            f"{mark} {name}",
            callback_data=f"srch:sort:{key}",
        ))
    rows = _chunk(btns, 2)
    rows.append([
        InlineKeyboardButton(
            "⬅️ قبلی", callback_data="srch:step:discount",
        ),
        InlineKeyboardButton(
            "➡️ بعدی", callback_data="srch:step:text",
        ),
    ])
    return InlineKeyboardMarkup(rows)


def _text_kb() -> InlineKeyboardMarkup:
    btns = [
        InlineKeyboardButton(
            name, callback_data=f"srch:cat:{key}",
        )
        for key, (name, _) in CATEGORY_PRESETS.items()
    ]
    rows = _chunk(btns, 2)
    rows.append([
        InlineKeyboardButton(
            "⬅️ قبلی", callback_data="srch:step:sort",
        ),
        InlineKeyboardButton(
            "❌ لغو", callback_data="srch:cancel",
        ),
    ])
    return InlineKeyboardMarkup(rows)


def _results_kb(
    page: int, total_pages: int, show_unverified: bool,
) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            "⬅️ قبلی", callback_data=f"srch:page:{page - 1}",
        ))
    nav.append(InlineKeyboardButton(
        f"{page + 1}/{total_pages}", callback_data="srch:noop",
    ))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(
            "بعدی ➡️", callback_data=f"srch:page:{page + 1}",
        ))

    toggle = (
        "🙈 پنهان‌کردن تأییدنشده‌ها"
        if show_unverified
        else "👁 نمایش تأییدنشده‌ها"
    )
    return InlineKeyboardMarkup([
        nav,
        [InlineKeyboardButton(
            toggle, callback_data="srch:toggle_unverified",
        )],
        [
            InlineKeyboardButton(
                "🔁 جستجوی جدید", callback_data="srch:start",
            ),
            InlineKeyboardButton(
                "❌ بستن", callback_data="srch:cancel",
            ),
        ],
    ])


# ====================== Entry ======================
async def start_wizard(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
):
    context.user_data["srch_q"] = SearchQuery()
    context.user_data["srch_page"] = 0
    text = (
        "🔍 <b>جستجوی هوشمند</b> — مرحله ۱ از ۴\n\n"
        "کدوم فروشگاه‌ها رو بگردم؟\n"
        "<i>می‌تونی چندتا انتخاب کنی.</i>"
    )
    kb = _store_kb(set(STORES.keys()))

    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=kb, parse_mode=ParseMode.HTML,
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text, reply_markup=kb, parse_mode=ParseMode.HTML,
            )
    else:
        await update.message.reply_text(
            text, reply_markup=kb, parse_mode=ParseMode.HTML,
        )
    return STORE


# ====================== Step 1: stores ======================
async def _cb_store(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
):
    q = update.callback_query
    await q.answer()
    key = q.data.split(":")[-1]
    sq = _get_q(context)

    if key == "all":
        sq.stores = list(STORES.keys())
    elif key in sq.stores:
        if len(sq.stores) == 1:
            await q.answer(
                "حداقل یک فروشگاه باید انتخاب بشه",
                show_alert=True,
            )
            return STORE
        sq.stores.remove(key)
    else:
        sq.stores.append(key)

    context.user_data["srch_q"] = sq
    await q.edit_message_reply_markup(
        reply_markup=_store_kb(set(sq.stores)),
    )
    return STORE


async def _to_discount(update, context):
    q = update.callback_query
    await q.answer()
    sq = _get_q(context)
    await q.edit_message_text(
        f"💰 <b>مرحله ۲ از ۴ — حداقل تخفیف</b>\n\n"
        f"فروشگاه‌ها: "
        f"{_esc(', '.join(STORES[s] for s in sq.stores))}\n\n"
        f"حداقل چند درصد تخفیف داشته باشه؟",
        reply_markup=_discount_kb(sq.min_discount),
        parse_mode=ParseMode.HTML,
    )
    return DISCOUNT


# ====================== Step 2: discount ======================
async def _cb_discount(update, context):
    q = update.callback_query
    await q.answer()
    sq = _get_q(context)
    sq.min_discount = float(q.data.split(":")[-1])
    context.user_data["srch_q"] = sq
    await q.edit_message_reply_markup(
        reply_markup=_discount_kb(sq.min_discount),
    )
    return DISCOUNT


async def _to_sort(update, context):
    q = update.callback_query
    await q.answer()
    sq = _get_q(context)
    await q.edit_message_text(
        f"📊 <b>مرحله ۳ از ۴ — ترتیب نمایش</b>\n\n"
        f"حداقل تخفیف: {sq.min_discount:.0f}٪",
        reply_markup=_sort_kb(sq.sort),
        parse_mode=ParseMode.HTML,
    )
    return SORT


# ====================== Step 3: sort ======================
async def _cb_sort(update, context):
    q = update.callback_query
    await q.answer()
    sq = _get_q(context)
    sq.sort = q.data.split(":")[-1]
    context.user_data["srch_q"] = sq
    await q.edit_message_reply_markup(
        reply_markup=_sort_kb(sq.sort),
    )
    return SORT


async def _to_text(update, context):
    q = update.callback_query
    await q.answer()
    sq = _get_q(context)
    await q.edit_message_text(
        "✍️ <b>مرحله ۴ از ۴ — محصول</b>\n\n"
        "اسم محصول یا دسته‌بندی رو بنویس:\n"
        "<i>می‌تونی یکی از دکمه‌ها رو بزنی یا خودت تایپ کنی.</i>\n\n"
        f"📋 خلاصه: "
        f"{_esc(', '.join(STORES[s] for s in sq.stores))} | "
        f"≥{sq.min_discount:.0f}٪ | "
        f"{_esc(SORT_OPTIONS.get(sq.sort, ''))}",
        reply_markup=_text_kb(),
        parse_mode=ParseMode.HTML,
    )
    return TEXT


# ====================== Step 4: run ======================
async def _cb_category(update, context):
    q = update.callback_query
    await q.answer()
    key = q.data.split(":")[-1]
    preset = CATEGORY_PRESETS.get(key)
    if not preset:
        return TEXT
    return await _run_and_render(update, context, preset[1])


async def _on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return TEXT
    context.user_data["srch_consume_next_text"] = True
    return await _run_and_render(update, context, text)


async def _run_and_render(update, context, text: str):
    sq = _get_q(context)
    sq.text = text
    context.user_data["srch_q"] = sq

    engine = get_engine()

    if update.callback_query:
        await update.callback_query.edit_message_text(
            f"⏳ در حال جستجو در "
            f"{_esc(', '.join(STORES[s] for s in sq.stores))} ..."
        )
        chat_id = update.callback_query.message.chat_id
    else:
        await update.message.reply_text(
            f"⏳ در حال جستجو در "
            f"{_esc(', '.join(STORES[s] for s in sq.stores))} ..."
        )
        chat_id = update.message.chat_id

    try:
        results = await engine.search_advanced(sq)
    except Exception as e:
        logger.exception("search_advanced failed")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ خطا در جستجو: {_esc(e)}",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    context.user_data["srch_results"] = results
    context.user_data["srch_page"] = 0
    await _render_results(chat_id, context)
    return ConversationHandler.END


# ====================== Render ======================
def _format_item(i: int, v) -> str:
    d = v.deal
    price = f"{d.price:,.0f}" if getattr(d, "price", None) else "—"
    url = _esc(getattr(d, "product_url", "") or "#")
    store = _esc(getattr(d, "store", ""))
    title = _esc((getattr(d, "title", "") or "")[:80])

    if v.real_discount > 0:
        disc = (
            f"📉 {v.real_discount:.0f}٪ ✅ "
            f"(اعتبار: {v.tier})"
        )
    else:
        disc = "⚠️ تخفیف تأییدنشده"

    return (
        f"<b>{i}. {title}</b>\n"
        f"💰 {price} تومان\n"
        f"{disc}\n"
        f"🏪 {store} · 🔗 <a href=\"{url}\">مشاهده</a>"
    )


async def _render_results(chat_id: int, context):
    results = context.user_data.get("srch_results") or []
    page = int(context.user_data.get("srch_page", 0) or 0)
    sq = _get_q(context)

    if not results:
        await context.bot.send_message(
            chat_id,
            "😔 هیچ نتیجه‌ای با این فیلترها پیدا نشد.\n\n"
            "💡 می‌تونی:\n"
            "• حداقل تخفیف رو کمتر کنی\n"
            "• «نمایش تأییدنشده‌ها» رو بزنی\n"
            "• یا فروشگاه‌های بیشتری انتخاب کنی",
            reply_markup=_results_kb(0, 1, sq.show_unverified),
            parse_mode=ParseMode.HTML,
        )
        return

    total_pages = max(1, (len(results) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    context.user_data["srch_page"] = page

    chunk = results[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    header = (
        f"📊 <b>{len(results)} نتیجه</b> از "
        f"{len(sq.stores)} فروشگاه\n"
        f"تخفیف ≥ {sq.min_discount:.0f}٪ | "
        f"{_esc(SORT_OPTIONS.get(sq.sort, ''))}\n"
        f"🔎 «{_esc(sq.text)}»\n"
    )
    body = "\n\n".join(
        _format_item(page * PAGE_SIZE + i + 1, v)
        for i, v in enumerate(chunk)
    )

    await context.bot.send_message(
        chat_id,
        header + "\n" + body,
        reply_markup=_results_kb(
            page, total_pages, sq.show_unverified,
        ),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cb_page(update, context):
    q = update.callback_query
    await q.answer()
    context.user_data["srch_page"] = int(
        q.data.split(":")[-1]
    )
    try:
        await q.message.delete()
    except Exception:
        pass
    await _render_results(q.message.chat_id, context)


async def cb_toggle_unverified(update, context):
    q = update.callback_query
    await q.answer()
    sq = _get_q(context)
    sq.show_unverified = not sq.show_unverified
    context.user_data["srch_q"] = sq

    try:
        results = await get_engine().search_advanced(sq)
        context.user_data["srch_results"] = results
        context.user_data["srch_page"] = 0
    except Exception:
        logger.exception("toggle search failed")

    try:
        await q.message.delete()
    except Exception:
        pass
    await _render_results(q.message.chat_id, context)


async def cb_noop(update, context):
    await update.callback_query.answer()


async def cancel(update, context):
    if update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                "❌ لغو شد. برای شروع مجدد /advsearch بزن."
            )
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(
            "❌ لغو شد. برای شروع مجدد /advsearch بزن."
        )
    context.user_data.pop("srch_q", None)
    context.user_data.pop("srch_results", None)
    return ConversationHandler.END


# ====================== Builder ======================
def build_search_wizard_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("advsearch", start_wizard),
            CallbackQueryHandler(
                start_wizard, pattern=r"^srch:start$",
            ),
        ],
        states={
            STORE: [
                CallbackQueryHandler(
                    _cb_store, pattern=r"^srch:store:",
                ),
                CallbackQueryHandler(
                    _to_discount, pattern=r"^srch:step:discount$",
                ),
                CallbackQueryHandler(
                    cancel, pattern=r"^srch:cancel$",
                ),
            ],
            DISCOUNT: [
                CallbackQueryHandler(
                    _cb_discount, pattern=r"^srch:disc:",
                ),
                CallbackQueryHandler(
                    _to_sort, pattern=r"^srch:step:sort$",
                ),
                CallbackQueryHandler(
                    start_wizard, pattern=r"^srch:step:store$",
                ),
                CallbackQueryHandler(
                    cancel, pattern=r"^srch:cancel$",
                ),
            ],
            SORT: [
                CallbackQueryHandler(
                    _cb_sort, pattern=r"^srch:sort:",
                ),
                CallbackQueryHandler(
                    _to_text, pattern=r"^srch:step:text$",
                ),
                CallbackQueryHandler(
                    _to_discount, pattern=r"^srch:step:discount$",
                ),
                CallbackQueryHandler(
                    cancel, pattern=r"^srch:cancel$",
                ),
            ],
            TEXT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _on_text,
                ),
                CallbackQueryHandler(
                    _cb_category, pattern=r"^srch:cat:",
                ),
                CallbackQueryHandler(
                    _to_sort, pattern=r"^srch:step:sort$",
                ),
                CallbackQueryHandler(
                    cancel, pattern=r"^srch:cancel$",
                ),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern=r"^srch:cancel$"),
        ],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )


__all__ = [
    "build_search_wizard_conversation",
    "start_wizard",
    "cb_page",
    "cb_toggle_unverified",
    "cb_noop",
]
