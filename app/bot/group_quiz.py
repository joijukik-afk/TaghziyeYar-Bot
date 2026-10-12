"""Quiz with fallback: try poll, else use inline keyboard."""

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

_active_polls: dict[str, dict] = {}
_chat_active_poll: dict[int, str] = {}
_active_games: dict[int, dict] = {}

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


def _options_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    letters = ["🅰️", "🅱️", "🅲", "🅳"]
    rows = []
    for i, opt in enumerate(options):
        letter = letters[i] if i < len(letters) else f"{i+1}."
        opt_text = opt if len(opt) <= 40 else opt[:38] + "..."
        rows.append([InlineKeyboardButton(f"{letter} {opt_text}", callback_data=f"gq_{i}")])
    return InlineKeyboardMarkup(rows)


def _live_text_inline(q_num, category, question, answers):
    lines = [
        f"🎮 {DIVIDER} 🎮",
        "   🧠 کوییز زنده تغذیه",
        f"🎮 {DIVIDER} 🎮",
        "",
        f"🏷 دسته: {_sanitize(category, 60)}",
        f"🎯 سوال: #{q_num}",
        "",
        f"❓ {_sanitize(question, 300)}",
        "",
        DIVIDER,
        f"⏱ فرصت: {TIMEOUT_SECONDS} ثانیه",
        "",
    ]
    if not answers:
        lines.append("🏆 پاسخ‌دهندگان:")
        lines.append("هنوز کسی جواب نداده — تو اولین باش!")
    else:
        lines.append(f"🏆 پاسخ‌دهندگان ({len(answers)}):")
        for a in answers:
            badge = _speed_badge(a["elapsed"])
            medal = _medal(a["position"])
            name = _sanitize(a["name"], 30)
            lines.append(f"{medal} {name} — {badge} {a['elapsed']:.1f}s — +{a['points']}")
    lines.append("")
    lines.append(DIVIDER)
    lines.append("🎯 هر کی سریع‌تر بزنه، امتیاز بیشتر!")
    return "\n".join(lines)


def _final_text_inline(q_num, question, correct_answer, explanation, answers):
    lines = [
        f"⏱ {DIVIDER} ⏱",
        "   زمان تموم شد!",
        f"⏱ {DIVIDER} ⏱",
        "",
        f"❓ {_sanitize(question, 300)}",
        "",
        f"✅ جواب درست: {_sanitize(correct_answer, 80)}",
        "",
    ]
    if explanation:
        lines.append(f"💡 {_sanitize(explanation, 300)}")
        lines.append("")
    lines.append(DIVIDER)
    if not answers:
        lines.append("😴 هیچ‌کس جواب درست نداد!")
    else:
        lines.append(f"🏆 نتایج نهایی ({len(answers)} پاسخ‌دهنده):")
        for a in answers:
            medal = _medal(a["position"])
            name = _sanitize(a["name"], 30)
            badge = _speed_badge(a["elapsed"])
            lines.append(f"{medal} {name} — {badge} {a['elapsed']:.1f}s — +{a['points']}")
    lines.append("")
    lines.append(DIVIDER)
    return "\n".join(lines)


# ============================================================
#  Try native poll
# ============================================================

async def _try_send_poll(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    chat_title: str,
) -> bool:
    bot = context.bot

    try:
        q = await generate_question()
    except Exception as e:
        logger.exception("Question gen failed: %s", e)
        return False

    q_num = int(_now().timestamp()) % 10000

    question_text = (
        f"🧠 کوییز تغذیه #{q_num}\n"
        f"🏷 دسته: {_sanitize(q.get('category', 'تغذیه'), 60)}\n\n"
        f"❓ {_sanitize(q['question'], 300)}"
    )

    options = [_sanitize(o, 100) for o in q["options"]]
    if len(options) < 2:
        return False

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
        logger.warning("Poll failed: %s", e)
        return False

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

    context.job_queue.run_once(
        finalize_poll_quiz,
        when=TIMEOUT_SECONDS + 2,
        chat_id=chat_id,
        data={"poll_id": poll_id},
        name=f"gq_finalize_{poll_id}",
    )

    logger.info("Quiz poll sent: %s in chat %s", poll_id, chat_id)
    return True


# ============================================================
#  Inline fallback
# ============================================================

async def _start_inline_quiz(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    chat_title: str,
    reply_to_message_id: int | None = None,
) -> None:
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

    text = _live_text_inline(q_num, q.get("category", "تغذیه"), q["question"], [])

    try:
        sent = await bot.send_message(
            chat_id=chat_id,
            text=with_signature(text),
            reply_markup=_options_keyboard(q["options"]),
            reply_to_message_id=reply_to_message_id,
        )
    except Exception as e:
        logger.exception("Failed to send inline quiz: %s", e)
        return

    _active_games[chat_id] = {
        "question": q,
        "message_id": sent.message_id,
        "started_at": _now(),
        "answers": [],
        "answered_user_ids": set(),
        "q_num": q_num,
        "ended": False,
        "chat_title": chat_title,
    }

    context.job_queue.run_once(
        finalize_inline_quiz,
        when=TIMEOUT_SECONDS,
        chat_id=chat_id,
        name=f"gq_timeout_{chat_id}",
    )


async def finalize_inline_quiz(context: ContextTypes.DEFAULT_TYPE) -> None:
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

    final = _final_text_inline(
        q_num=game["q_num"],
        question=q["question"],
        correct_answer=correct_answer,
        explanation=q.get("explanation", ""),
        answers=game["answers"],
    )
    next_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 سوال بعدی", callback_data="gq_next")],
    ])

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=game["message_id"],
            text=with_signature(final),
            reply_markup=next_kb,
        )
    except Exception as e:
        logger.warning("final inline edit failed: %s", e)

    _active_games.pop(chat_id, None)


# ============================================================
#  /quiz
# ============================================================

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None:
        return

    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title or ""

    existing_poll_id = _chat_active_poll.get(chat_id)
    if existing_poll_id and existing_poll_id in _active_polls:
        if not _active_polls[existing_poll_id]["finalized"]:
            await update.message.reply_text(
                with_signature("⏳ یه کوییز در حال اجراست — صبر کن تموم بشه."),
            )
            return
    if chat_id in _active_games and not _active_games[chat_id].get("ended"):
        await update.message.reply_text(
            with_signature("⏳ یه کوییز در حال اجراست — صبر کن تموم بشه."),
        )
        return

    ok = await _try_send_poll(context, chat_id, chat_title)
    if ok:
        return

    logger.info("Poll not allowed in chat %s — using inline fallback", chat_id)
    await _start_inline_quiz(context, chat_id, chat_title)


# ============================================================
#  Poll answer
# ============================================================

async def on_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
#  Inline answer
# ============================================================

async def on_inline_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        await query.answer("✅ قبلاً جواب دادید!", show_alert=False)
        return

    if len(game["answers"]) >= MAX_PLAYERS:
        await query.answer("👥 تعداد پر شده!", show_alert=False)
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
        except Exception:
            pass
        return

    elapsed = (_now() - game["started_at"]).total_seconds()
    points = _points_for_elapsed(elapsed)
    position = len(game["answers"]) + 1

    display_name = (
        f"@{user.username}" if user.username
        else (user.first_name or user.last_name or "کاربر")
    )

    game["answers"].append({
        "user_id": user.id,
        "name": display_name,
        "elapsed": elapsed,
        "points": points,
        "position": position,
    })

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
        logger.warning("record answer failed: %s", e)

    await query.answer(f"✅ درست! 🏅 {position} — +{points} امتیاز", show_alert=False)

    text = _live_text_inline(game["q_num"], q.get("category", "تغذیه"), q["question"], game["answers"])
    try:
        await query.edit_message_text(
            text=with_signature(text),
            reply_markup=_options_keyboard(q["options"]),
        )
    except Exception as e:
        err = str(e).lower()
        if "not modified" not in err:
            logger.debug("inline edit failed: %s", e)


# ============================================================
#  Finalize poll
# ============================================================

async def finalize_poll_quiz(context: ContextTypes.DEFAULT_TYPE) -> None:
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
            pts = _points_for_elapsed(a["elapsed"])
            lines.append(f"{medal} {name} — {badge} {a['elapsed']:.1f}s — +{pts}")
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
        logger.warning("final poll message failed: %s", e)
    _active_polls.pop(poll_id, None)


# ============================================================
#  Helper for gq_next
# ============================================================

async def send_quiz_from_callback(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    chat_title: str,
) -> None:
    for j in context.job_queue.get_jobs_by_name(f"gq_finalize_{chat_id}"):
        j.schedule_removal()
    for j in context.job_queue.get_jobs_by_name(f"gq_timeout_{chat_id}"):
        j.schedule_removal()

    ok = await _try_send_poll(context, chat_id, chat_title)
    if ok:
        return
    await _start_inline_quiz(context, chat_id, chat_title)


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
