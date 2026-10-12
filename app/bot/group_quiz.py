"""Live AI-powered group quiz — everyone can participate."""

import logging
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

from app.database import repository as repo
from app.services.quiz_ai import generate_question
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

_active_games: dict[int, dict] = {}

TIMEOUT_SECONDS = 30
MAX_PLAYERS = 20

DIVIDER = "━━━━━━━━━━━━━━━━"


def _esc(text: str) -> str:
    if not text:
        return ""
    try:
        return escape_markdown(text, version=1)
    except Exception:
        return text


def _points_for_elapsed(elapsed: float) -> int:
    if elapsed <= 3:
        return 10
    if elapsed <= 6:
        return 8
    if elapsed <= 10:
        return 6
    if elapsed <= 15:
        return 4
    if elapsed <= 22:
        return 2
    return 1


def _speed_badge(elapsed: float) -> str:
    if elapsed <= 3:
        return "🚀"
    if elapsed <= 6:
        return "⚡"
    if elapsed <= 10:
        return "💨"
    if elapsed <= 15:
        return "👍"
    if elapsed <= 22:
        return "👌"
    return "🐢"


def _medal(pos: int) -> str:
    if pos == 1:
        return "🥇"
    if pos == 2:
        return "🥈"
    if pos == 3:
        return "🥉"
    return f"`{pos}.`"


def _options_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    letters = ["🅰️", "🅱️", "🅲", "🅳"]
    rows = []
    for i, opt in enumerate(options):
        letter = letters[i] if i < len(letters) else f"{i+1}."
        opt_text = opt if len(opt) <= 45 else opt[:42] + "..."
        rows.append([InlineKeyboardButton(f"{letter} {opt_text}", callback_data=f"gq_{i}")])
    return InlineKeyboardMarkup(rows)


def _format_live_message(
    q_num: int,
    category: str,
    question: str,
    seconds_left: int,
    answers: list[dict],
) -> str:
    lines = [
        f"🎮 {DIVIDER} 🎮",
        "   🧠 **کوییز زنده تغذیه**",
        f"🎮 {DIVIDER} 🎮",
        "",
        f"🏷 دسته: *{_esc(category)}*",
        f"🎯 سوال: `#{q_num}`",
        "",
        f"❓ {_esc(question)}",
        "",
        DIVIDER,
        f"⏱ **{seconds_left} ثانیه** مونده",
        "",
    ]

    if not answers:
        lines.append("🏆 **پاسخ‌دهندگان:**")
        lines.append("_هنوز کسی جواب نداده — تو اولین باش!_")
    else:
        lines.append(f"🏆 **پاسخ‌دهندگان ({len(answers)}):**")
        for a in answers:
            badge = _speed_badge(a["elapsed"])
            medal = _medal(a["position"])
            name = _esc(a["name"])
            lines.append(
                f"{medal} {name} — {badge} {a['elapsed']:.1f}s — **+{a['points']}**"
            )

    lines.append("")
    lines.append(DIVIDER)
    lines.append("🎯 **هر کی سریع‌تر بزنه، امتیاز بیشتر!**")
    lines.append("💡 همه می‌تونن شرکت کنن — تا ۳۰ ثانیه")

    return "\n".join(lines)


def _format_final_message(
    q_num: int,
    question: str,
    correct_answer: str,
    explanation: str,
    answers: list[dict],
) -> str:
    lines = [
        f"⏱ {DIVIDER} ⏱",
        "   **زمان تموم شد!**",
        f"⏱ {DIVIDER} ⏱",
        "",
        f"❓ {_esc(question)}",
        "",
        f"✅ جواب درست: **{_esc(correct_answer)}**",
        "",
    ]

    if explanation:
        lines.append(f"💡 {_esc(explanation)}")
        lines.append("")

    lines.append(DIVIDER)

    if not answers:
        lines.append("😴 **هیچ‌کس جواب درست نداد!**")
    else:
        lines.append(f"🏆 **نتایج نهایی ({len(answers)} پاسخ‌دهنده):**")
        for a in answers:
            medal = _medal(a["position"])
            name = _esc(a["name"])
            badge = _speed_badge(a["elapsed"])
            lines.append(
                f"{medal} {name} — {badge} {a['elapsed']:.1f}s — **+{a['points']}**"
            )

    lines.append("")
    lines.append(DIVIDER)
    lines.append("🎮 برای کوییز بعدی: /quiz")
    lines.append("🏆 برای جدول: /leaderboard")
    lines.append("📊 برای آمار شخصی: /mystats")

    return "\n".join(lines)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================
#  /quiz
# ============================================================

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None:
        return

    chat_id = update.effective_chat.id

    if chat_id in _active_games:
        await update.message.reply_text(
            with_signature("⏳ یه کوییز در حال اجراست — صبر کن تموم بشه."),
            parse_mode="Markdown",
        )
        return

    loading = await update.message.reply_text(
        with_signature("🧠 **در حال ساخت سوال...**\n\n_چند لحظه صبر کن_"),
        parse_mode="Markdown",
    )

    q = await generate_question()
    q_num = int(_now().timestamp()) % 10000

    text = _format_live_message(
        q_num=q_num,
        category=q.get("category", "تغذیه"),
        question=q["question"],
        seconds_left=TIMEOUT_SECONDS,
        answers=[],
    )
    keyboard = _options_keyboard(q["options"])

    try:
        await loading.edit_text(
            text=with_signature(text),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.warning("Failed to edit loading msg: %s", e)
        return

    _active_games[chat_id] = {
        "question": q,
        "message_id": loading.message_id,
        "started_at": _now(),
        "answers": [],
        "answered_user_ids": set(),
        "q_num": q_num,
        "ended": False,
        "chat_title": update.effective_chat.title or "",
    }

    context.job_queue.run_once(
        _timeout_callback,
        when=TIMEOUT_SECONDS,
        chat_id=chat_id,
        name=f"gq_timeout_{chat_id}",
    )


async def _timeout_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    if job is None:
        return
    chat_id = job.chat_id
    game = _active_games.get(chat_id)
    if game is None or game["ended"]:
        return

    game["ended"] = True
    q = game["question"]
    correct_answer = q["options"][q["correct"]]

    text = _format_final_message(
        q_num=game["q_num"],
        question=q["question"],
        correct_answer=correct_answer,
        explanation=q.get("explanation", ""),
        answers=game["answers"],
    )

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=game["message_id"],
            text=with_signature(text),
            parse_mode="Markdown",
            reply_markup=None,
        )
    except Exception as e:
        logger.warning("Failed to edit timeout message: %s", e)

    _active_games.pop(chat_id, None)


# ============================================================
#  answer callback
# ============================================================

async def handle_group_quiz_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    if query is None:
        return

    chat_id = update.effective_chat.id if update.effective_chat else None
    user = query.from_user

    if chat_id is None or user is None:
        await query.answer()
        return

    game = _active_games.get(chat_id)
    if game is None:
        await query.answer("⌛ این کوییز تموم شده!", show_alert=False)
        return

    elapsed = (_now() - game["started_at"]).total_seconds()
    if game["ended"] or elapsed > TIMEOUT_SECONDS:
        await query.answer("⏱ زمان تموم شده!", show_alert=False)
        return

    if user.id in game["answered_user_ids"]:
        await query.answer("✅ شما قبلاً جواب دادید!", show_alert=False)
        return

    if len(game["answers"]) >= MAX_PLAYERS:
        await query.answer("👥 تعداد شرکت‌کنندگان پر شده!", show_alert=False)
        return

    try:
        selected = int((query.data or "").replace("gq_", ""))
    except ValueError:
        await query.answer()
        return

    q = game["question"]
    correct = (selected == q["correct"])

    game["answered_user_ids"].add(user.id)

    if not correct:
        await query.answer("❌ اشتباه! دفعه بعد بهتر.", show_alert=False)
        try:
            await repo.record_quiz_wrong(user.id, chat_id)
        except Exception as e:
            logger.warning("Failed to record wrong: %s", e)
        return

    # correct answer
    elapsed = (_now() - game["started_at"]).total_seconds()
    points = _points_for_elapsed(elapsed)
    position = len(game["answers"]) + 1

    display_name = (
        f"@{user.username}" if user.username
        else (user.first_name or user.last_name or "کاربر")
    )

    answer_entry = {
        "user_id": user.id,
        "name": display_name,
        "elapsed": elapsed,
        "points": points,
        "position": position,
    }
    game["answers"].append(answer_entry)

    try:
        await repo.record_quiz_answer(
            telegram_id=user.id,
            display_name=display_name,
            chat_id=chat_id,
            chat_title=game.get("chat_title", ""),
            points=points,
            elapsed_ms=int(elapsed * 1000),
            question_text=q["question"],
            position=position,
        )
    except Exception as e:
        logger.warning("Failed to record answer: %s", e)

    await query.answer(
        f"✅ درست! 🏅 {position} — +{points} امتیاز",
        show_alert=False,
    )

    seconds_left = max(0, int(TIMEOUT_SECONDS - elapsed))
    live_text = _format_live_message(
        q_num=game["q_num"],
        category=q.get("category", "تغذیه"),
        question=q["question"],
        seconds_left=seconds_left,
        answers=game["answers"],
    )

    try:
        await query.edit_message_text(
            text=with_signature(live_text),
            parse_mode="Markdown",
            reply_markup=_options_keyboard(q["options"]),
        )
    except Exception as e:
        logger.debug("Failed to edit live msg: %s", e)


# ============================================================
#  /leaderboard
# ============================================================

async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None:
        return

    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title or "این گروه"

    try:
        entries = await repo.get_leaderboard(chat_id, limit=10, week=True)
    except Exception as e:
        logger.warning("Failed to load leaderboard: %s", e)
        entries = []

    lines = [
        f"🏆 {DIVIDER} 🏆",
        "   **جدول قهرمانان هفته**",
        f"   🏟 {_esc(chat_title)}",
        f"🏆 {DIVIDER} 🏆",
        "",
    ]

    if not entries:
        lines.append("😴 **هنوز کسی تو کوییز شرکت نکرده.**")
        lines.append("")
        lines.append("🎮 برای شروع: /quiz")
        lines.append("")
        lines.append(DIVIDER)
    else:
        for i, e in enumerate(entries):
            pos = i + 1
            medal = _medal(pos)
            name = _esc(e.display_name or "کاربر")
            streak_icon = ""
            if e.streak >= 3:
                streak_icon = f" 🔥×{e.streak}"
            lines.append(
                f"{medal} {name} — **{e.points}** امتیاز{streak_icon}"
            )
        lines.append("")
        lines.append(DIVIDER)
        lines.append("_🏁 هر شنبه ریست می‌شه_")
        lines.append("_🎮 برای بازی: /quiz_")

    await update.message.reply_text(
        with_signature("\n".join(lines)),
        parse_mode="Markdown",
    )


# ============================================================
#  /mystats
# ============================================================

async def cmd_mystats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None:
        return

    user = update.effective_user
    if user is None:
        return

    chat_id = update.effective_chat.id

    try:
        rank, points, streak = await repo.get_user_rank(user.id, chat_id)
    except Exception as e:
        logger.warning("Failed to load user stats: %s", e)
        rank, points, streak = 0, 0, 0

    name = (
        f"@{user.username}" if user.username
        else (user.first_name or "کاربر")
    )

    lines = [
        f"📊 {DIVIDER} 📊",
        "   **آمار تو**",
        f"📊 {DIVIDER} 📊",
        "",
        f"👤 {_esc(name)}",
    ]

    if rank == 0:
        lines.append("😴 هنوز تو کوییز شرکت نکردی.")
        lines.append("")
        lines.append("_برای شروع: /quiz_")
    else:
        medal = _medal(rank) if rank <= 3 else "📊"
        streak_line = ""
        if streak >= 3:
            streak_line = f"\n🔥 استریک: **{streak}** برد پشت‌سرهم"
        lines.append(f"{medal} رتبه: **{rank}**")
        lines.append(f"🎯 امتیاز این هفته: **{points}**{streak_line}")
        lines.append("")
        lines.append("_برای جدول کامل: /leaderboard_")

    await update.message.reply_text(
        with_signature("\n".join(lines)),
        parse_mode="Markdown",
    )
