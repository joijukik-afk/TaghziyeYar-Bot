"""Quiz with Telegram's native Poll feature (live timer built-in)."""

import logging
from datetime import datetime, timezone

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Poll,
    Update,
)
from telegram.ext import ContextTypes

from app.database import repository as repo
from app.services.quiz_ai import generate_question
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

# poll_id -> game state
_active_polls: dict[str, dict] = {}
# chat_id -> poll_id (for "one active quiz per chat")
_chat_active_poll: dict[int, str] = {}

TIMEOUT_SECONDS = 30
MAX_PLAYERS = 20

DIVIDER = "━━━━━━━━━━━━━━━━"


def _sanitize(text: str, max_len: int = 400) -> str:
    if not text:
        return ""
    return str(text)[:max_len].strip()


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
    return f"{pos}."


def _now():
    return datetime.now(timezone.utc)


# ============================================================
#  Send a quiz poll
# ============================================================

async def _send_quiz_poll(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    chat_title: str,
) -> None:
    """Generate question + send as native Telegram quiz poll."""
    bot = context.bot

    try:
        q = await generate_question()
    except Exception as e:
        logger.exception("Question gen failed: %s", e)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=with_signature("😔 خطا در ساخت سوال. دوباره /quiz بزن."),
            )
        except Exception:
            pass
        return

    q_num = int(_now().timestamp()) % 10000

    # Build question text
    question_text = (
        f"🧠 کوییز تغذیه #{q_num}\n"
        f"🏷 دسته: {_sanitize(q.get('category', 'تغذیه'), 60)}\n\n"
        f"❓ {_sanitize(q['question'], 300)}"
    )

    # Validate options (Telegram requires 2-10 options)
    options = [_sanitize(o, 100) for o in q["options"]]
    if len(options) < 2:
        logger.warning("Too few options, aborting")
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=with_signature("😔 خطا در ساخت سوال. دوباره /quiz بزن."),
            )
        except Exception:
            pass
        return

    correct_idx = int(q["correct"])
    if correct_idx < 0 or correct_idx >= len(options):
        correct_idx = 0

    explanation = _sanitize(q.get("explanation", ""), 200)

    try:
        msg = await bot.send_poll(
            chat_id=chat_id,
            question=question_text,
            options=options,
            type=Poll.QUIZ,
            correct_option_id=correct_idx,
            is_anonymous=False,
            open_period=TIMEOUT_SECONDS,
            explanation=explanation if explanation else None,
        )
    except Exception as e:
        logger.exception("Failed to send poll: %s", e)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=with_signature("😔 خطا در ارسال کوییز. دوباره تلاش کن."),
            )
        except Exception:
            pass
        return

    poll_id = msg.poll.id

    _active_polls[poll_id] = {
        "chat_id": chat_id,
        "chat_title": chat_title,
        "question": q,
        "started_at": _now(),
        "message_id": msg.message_id,
        "q_num": q_num,
        "answers": [],
        "answered_user_ids": set(),
        "finalized": False,
    }
    _chat_active_poll[chat_id] = poll_id

    # Schedule finalize job (2 seconds after poll closes)
    context.job_queue.run_once(
        finalize_quiz,
        when=TIMEOUT_SECONDS + 2,
        chat_id=chat_id,
        data={"poll_id": poll_id},
        name=f"gq_finalize_{poll_id}",
    )

    logger.info("Quiz poll sent: %s in chat %s", poll_id, chat_id)


# ============================================================
#  /quiz
# ============================================================

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None:
        return

    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title or ""

    # If there's already an active quiz
    existing_poll_id = _chat_active_poll.get(chat_id)
    if existing_poll_id and existing_poll_id in _active_polls:
        game = _active_polls[existing_poll_id]
        if not game["finalized"]:
            await update.message.reply_text(
                with_signature("⏳ یه کوییز در حال اجراست — صبر کن تموم بشه."),
            )
            return

    await _send_quiz_poll(context, chat_id, chat_title)


# ============================================================
#  Poll answer handler
# ============================================================

async def on_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called each time a user answers the poll."""
    answer = update.poll_answer
    if answer is None:
        return

    poll_id = answer.poll_id
    game = _active_polls.get(poll_id)
    if game is None:
        return

    user = answer.user
    if user is None:
        return

    if user.id in game["answered_user_ids"]:
        return

    if len(game["answers"]) >= MAX_PLAYERS:
        return

    selected = answer.option_ids[0] if answer.option_ids else -1
    is_correct = (selected == game["question"]["correct"])

    elapsed = (_now() - game["started_at"]).total_seconds()

    display_name = (
        f"@{user.username}" if user.username
        else (user.first_name or user.last_name or "کاربر")
    )

    game["answered_user_ids"].add(user.id)
    game["answers"].append({
        "user_id": user.id,
        "name": display_name,
        "elapsed": elapsed,
        "is_correct": is_correct,
        "selected": selected,
    })

    # ---- Persist to DB ----
    if is_correct:
        points = _points_for_elapsed(elapsed)
        position = sum(1 for a in game["answers"] if a["is_correct"])
        try:
            await repo.record_quiz_answer(
                telegram_id=user.id,
                display_name=display_name,
                chat_id=game["chat_id"],
                chat_title=game["chat_title"],
                points=points,
                elapsed_ms=int(elapsed * 1000),
                question_text=game["question"]["question"],
                position=position,
            )
        except Exception as e:
            logger.warning("record answer failed: %s", e)
    else:
        try:
            await repo.record_quiz_wrong(user.id, game["chat_id"])
        except Exception:
            pass


# ============================================================
#  Finalize
# ============================================================

async def finalize_quiz(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send summary message after the poll closes."""
    job = context.job
    if job is None:
        return
    data = job.data or {}
    poll_id = data.get("poll_id")
    if not poll_id:
        return

    game = _active_polls.get(poll_id)
    if game is None or game["finalized"]:
        return

    game["finalized"] = True

    if _chat_active_poll.get(game["chat_id"]) == poll_id:
        _chat_active_poll.pop(game["chat_id"], None)

    q = game["question"]
    answers = game["answers"]
    correct_answers = [a for a in answers if a["is_correct"]]
    correct_answers.sort(key=lambda a: a["elapsed"])

    lines = [
        f"⏱ {DIVIDER} ⏱",
        f"   نتایج کوییز #{game['q_num']}",
        f"⏱ {DIVIDER} ⏱",
        "",
        f"❓ {_sanitize(q['question'], 300)}",
        "",
        f"✅ جواب درست: {_sanitize(q['options'][q['correct']], 80)}",
    ]

    explanation = q.get("explanation", "")
    if explanation:
        lines.append("")
        lines.append(f"💡 {_sanitize(explanation, 300)}")

    lines.append("")
    lines.append(DIVIDER)

    if not answers:
        lines.append("😴 هیچ‌کس شرکت نکرد!")
    elif not correct_answers:
        lines.append(f"😔 هیچ‌کس درست جواب نداد! ({len(answers)} پاسخ‌دهنده)")
    else:
        lines.append(f"🏆 برندگان ({len(correct_answers)}):")
        for i, a in enumerate(correct_answers[:10]):
            pos = i + 1
            medal = _medal(pos)
            name = _sanitize(a["name"], 30)
            badge = _speed_badge(a["elapsed"])
            points = _points_for_elapsed(a["elapsed"])
            lines.append(
                f"{medal} {name} — {badge} {a['elapsed']:.1f}s — +{points}"
            )
        wrong_count = len(answers) - len(correct_answers)
        if wrong_count > 0:
            lines.append("")
            lines.append(f"❌ {wrong_count} نفر اشتباه جواب دادن")

    lines.append("")
    lines.append(DIVIDER)

    next_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 سوال بعدی", callback_data="gq_next")],
    ])

    try:
        await context.bot.send_message(
            chat_id=game["chat_id"],
            text=with_signature("\n".join(lines)),
            reply_markup=next_kb,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning("final message failed: %s", e)

    _active_polls.pop(poll_id, None)


# ============================================================
#  Helper for gq_next
# ============================================================

async def send_quiz_from_callback(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    chat_title: str,
) -> None:
    """Start a new poll from the 'next question' button."""
    for j in context.job_queue.get_jobs_by_name(f"gq_finalize_{chat_id}"):
        j.schedule_removal()

    await _send_quiz_poll(context, chat_id, chat_title)


# ============================================================
#  /leaderboard
# ============================================================

async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None:
        return

    chat_id = update.effective_chat.id
    chat_title = _sanitize(update.effective_chat.title or "این گروه", 60)

    try:
        entries = await repo.get_leaderboard(chat_id, limit=10, week=True)
    except Exception as e:
        logger.warning("leaderboard failed: %s", e)
        entries = []

    lines = [
        f"🏆 {DIVIDER} 🏆",
        "   جدول قهرمانان هفته",
        f"   🏟 {chat_title}",
        f"🏆 {DIVIDER} 🏆",
        "",
    ]
    if not entries:
        lines.append("😴 هنوز کسی تو کوییز شرکت نکرده.")
        lines.append("")
        lines.append("🎮 برای شروع: /quiz")
    else:
        for i, e in enumerate(entries):
            medal = _medal(i + 1)
            name = _sanitize(e.display_name or "کاربر", 30)
            streak = f" 🔥×{e.streak}" if e.streak >= 3 else ""
            lines.append(f"{medal} {name} — {e.points} امتیاز{streak}")
        lines.append("")
        lines.append(DIVIDER)
        lines.append("🏁 هر شنبه ریست می‌شه")

    await update.message.reply_text(with_signature("\n".join(lines)))


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
        logger.warning("mystats failed: %s", e)
        rank, points, streak = 0, 0, 0

    name = _sanitize(
        f"@{user.username}" if user.username else (user.first_name or "کاربر"),
        40,
    )

    lines = [
        f"📊 {DIVIDER} 📊",
        "   آمار تو",
        f"📊 {DIVIDER} 📊",
        "",
        f"👤 {name}",
    ]
    if rank == 0:
        lines.append("😴 هنوز تو کوییز شرکت نکردی.")
        lines.append("")
        lines.append("برای شروع: /quiz")
    else:
        medal = _medal(rank) if rank <= 3 else "📊"
        streak_line = f"\n🔥 استریک: {streak} برد" if streak >= 3 else ""
        lines.append(f"{medal} رتبه: {rank}")
        lines.append(f"🎯 امتیاز: {points}{streak_line}")
        lines.append("")
        lines.append("برای جدول: /leaderboard")

    await update.message.reply_text(with_signature("\n".join(lines)))
