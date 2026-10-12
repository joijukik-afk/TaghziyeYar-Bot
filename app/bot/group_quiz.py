"""Live group quiz with REAL working live timer."""

import asyncio
import logging
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.database import repository as repo
from app.services.quiz_ai import generate_question
from app.utils.message_formatter import with_signature

logger = logging.getLogger(__name__)

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


def _options_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    letters = ["🅰️", "🅱️", "🅲", "🅳"]
    rows = []
    for i, opt in enumerate(options):
        letter = letters[i] if i < len(letters) else f"{i+1}."
        opt_text = opt if len(opt) <= 40 else opt[:38] + "..."
        rows.append([InlineKeyboardButton(f"{letter} {opt_text}", callback_data=f"gq_{i}")])
    return InlineKeyboardMarkup(rows)


def _progress_bar(seconds_left: int) -> str:
    total = TIMEOUT_SECONDS
    filled = int((seconds_left / total) * 10)
    filled = max(0, min(10, filled))
    return "🟩" * filled + "⬜" * (10 - filled)


def _live_text(q_num, category, question, seconds_left, answers):
    bar = _progress_bar(seconds_left)
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
        f"⏱ {seconds_left} ثانیه مونده",
        f"{bar}",
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


def _final_text(q_num, question, correct_answer, explanation, answers):
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


def _now():
    return datetime.now(timezone.utc)


# ============================================================
#  LIVE TIMER — asyncio task (bulletproof)
# ============================================================

async def _live_timer_loop(bot, chat_id: int) -> None:
    """Run continuously, update the quiz message every second."""
    try:
        while True:
            await asyncio.sleep(1.0)

            game = _active_games.get(chat_id)
            if game is None or game.get("ended"):
                return

            elapsed = (_now() - game["started_at"]).total_seconds()
            seconds_left = max(0, int(TIMEOUT_SECONDS - elapsed))
            q = game["question"]

            # ---- time's up ----
            if seconds_left <= 0:
                game["ended"] = True
                correct_answer = q["options"][q["correct"]]
                final = _final_text(
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
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=game["message_id"],
                        text=final,
                        reply_markup=next_kb,
                    )
                except Exception as e:
                    logger.warning("final edit failed: %s", e)
                return

            # ---- skip if seconds unchanged ----
            if seconds_left == game.get("last_seconds"):
                continue

            game["last_seconds"] = seconds_left

            # ---- update ----
            text = _live_text(
                q_num=game["q_num"],
                category=q.get("category", "تغذیه"),
                question=q["question"],
                seconds_left=seconds_left,
                answers=game["answers"],
            )

            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=game["message_id"],
                    text=text,
                    reply_markup=_options_keyboard(q["options"]),
                )
            except Exception as e:
                err = str(e).lower()
                if "not modified" in err:
                    pass
                elif "retry" in err or "flood" in err or "too many" in err:
                    # wait longer next time
                    await asyncio.sleep(1.0)
                else:
                    logger.debug("timer edit failed: %s", e)

    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.exception("Timer loop crashed: %s", e)


# ============================================================
#  /quiz
# ============================================================

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_chat is None:
        return

    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title or ""

    if chat_id in _active_games:
        await update.message.reply_text(
            with_signature("⏳ یه کوییز در حال اجراست — صبر کن تموم بشه."),
        )
        return

    # cancel previous task if any
    old = _active_games.get(chat_id, {}).get("task")
    if old is not None and not old.done():
        old.cancel()

    loading = await update.message.reply_text(
        with_signature("🧠 در حال ساخت سوال...\n\nچند لحظه صبر کن"),
    )

    try:
        q = await generate_question()
    except Exception as e:
        logger.exception("Question gen failed: %s", e)
        try:
            await loading.edit_text(
                with_signature("😔 خطا در ساخت سوال. دوباره /quiz بزن.")
            )
        except Exception:
            pass
        return

    q_num = int(_now().timestamp()) % 10000

    text = _live_text(q_num, q.get("category", "تغذیه"), q["question"], TIMEOUT_SECONDS, [])
    keyboard = _options_keyboard(q["options"])

    try:
        await loading.edit_text(text=text, reply_markup=keyboard)
    except Exception as e:
        logger.exception("Failed to edit loading msg: %s", e)
        return

    game = {
        "question": q,
        "message_id": loading.message_id,
        "started_at": _now(),
        "answers": [],
        "answered_user_ids": set(),
        "q_num": q_num,
        "ended": False,
        "chat_title": chat_title,
        "last_seconds": TIMEOUT_SECONDS,
        "task": None,
    }
    _active_games[chat_id] = game

    # Start live timer task (store in game so it isn't garbage collected)
    task = asyncio.create_task(_live_timer_loop(context.bot, chat_id))
    game["task"] = task


# ============================================================
#  Answer handler
# ============================================================

async def handle_group_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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

    # ---- wrong ----
    if not correct:
        await query.answer("❌ اشتباه! دفعه بعد بهتر.", show_alert=False)
        try:
            await repo.record_quiz_wrong(user.id, chat_id)
        except Exception:
            pass
        return

    # ---- correct ----
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
    # live timer will refresh the message on next tick


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
