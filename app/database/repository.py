"""CRUD helpers — thin wrappers around the SQLAlchemy session."""

from datetime import date, timedelta

from sqlalchemy import desc, func, select

from app.database.models import (
    AuditLog,
    Group,
    Profile,
    User,
    WeightLog,
)
from app.database.quiz_models import QuizLeaderboard, QuizLog
from app.database.session import session_scope


# ---------------------------------------------------------------- users
async def get_or_create_user(
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> User:
    async with session_scope() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
            )
            session.add(user)
            await session.flush()
            profile = Profile(user_id=user.id)
            session.add(profile)
            await session.flush()
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
        await session.refresh(user)
        return user


async def get_user_by_telegram_id(telegram_id: int) -> User | None:
    async with session_scope() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------- groups
async def get_or_create_group(chat_id: int, title: str | None) -> Group:
    async with session_scope() as session:
        result = await session.execute(
            select(Group).where(Group.chat_id == chat_id)
        )
        group = result.scalar_one_or_none()
        if group is None:
            group = Group(chat_id=chat_id, title=title)
            session.add(group)
        else:
            group.title = title
            group.is_active = True
        await session.flush()
        await session.refresh(group)
        return group


async def list_all_groups() -> list[Group]:
    async with session_scope() as session:
        result = await session.execute(
            select(Group).where(Group.is_active == True)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------- profile
async def get_profile(user_id: int) -> Profile | None:
    async with session_scope() as session:
        result = await session.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        return result.scalar_one_or_none()


async def update_profile(user_id: int, **fields) -> Profile | None:
    async with session_scope() as session:
        result = await session.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            return None
        for key, value in fields.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        await session.flush()
        await session.refresh(profile)
        return profile


# ---------------------------------------------------------------- weight
async def log_weight(user_id: int, weight_kg: float) -> WeightLog:
    async with session_scope() as session:
        entry = WeightLog(user_id=user_id, weight_kg=weight_kg)
        session.add(entry)
        await session.flush()
        await session.refresh(entry)
        return entry


async def list_weights(user_id: int, limit: int = 30) -> list[WeightLog]:
    async with session_scope() as session:
        result = await session.execute(
            select(WeightLog)
            .where(WeightLog.user_id == user_id)
            .order_by(WeightLog.logged_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


# ---------------------------------------------------------------- audit
async def audit(telegram_id: int | None, event: str, details: str | None = None) -> None:
    async with session_scope() as session:
        session.add(
            AuditLog(telegram_id=telegram_id, event=event, details=details)
        )


# ================================================================
#  QUIZ
# ================================================================

def _current_week_start() -> str:
    """Return the Saturday of the current week (YYYY-MM-DD)."""
    today = date.today()
    days_since_saturday = (today.weekday() - 5) % 7
    saturday = today - timedelta(days=days_since_saturday)
    return saturday.isoformat()


async def record_quiz_answer(
    telegram_id: int,
    display_name: str,
    chat_id: int,
    chat_title: str,
    points: int,
    elapsed_ms: int,
    question_text: str,
    position: int,
) -> None:
    """Record a correct quiz answer."""
    week = _current_week_start()

    async with session_scope() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(telegram_id=telegram_id, first_name=display_name)
            session.add(user)
            await session.flush()
            session.add(Profile(user_id=user.id))
            await session.flush()

        result = await session.execute(
            select(QuizLeaderboard).where(
                QuizLeaderboard.user_id == user.id,
                QuizLeaderboard.chat_id == chat_id,
                QuizLeaderboard.week_start == week,
            )
        )
        entry = result.scalar_one_or_none()

        if entry is None:
            entry = QuizLeaderboard(
                user_id=user.id,
                telegram_id=telegram_id,
                display_name=display_name,
                chat_id=chat_id,
                chat_title=chat_title,
                week_start=week,
                points=points,
                wins=1,
                total_games=1,
                correct_answers=1,
                streak=1,
                best_streak=1,
            )
            session.add(entry)
        else:
            entry.points += points
            entry.wins += 1
            entry.total_games += 1
            entry.correct_answers += 1
            entry.streak += 1
            if entry.streak > entry.best_streak:
                entry.best_streak = entry.streak
            entry.display_name = display_name

        session.add(
            QuizLog(
                chat_id=chat_id,
                question=question_text[:500],
                user_telegram_id=telegram_id,
                user_name=display_name,
                points=points,
                elapsed_ms=elapsed_ms,
                position=position,
            )
        )
        await session.flush()


async def record_quiz_wrong(telegram_id: int, chat_id: int) -> None:
    """Record a wrong answer (resets streak)."""
    week = _current_week_start()
    async with session_scope() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return

        result = await session.execute(
            select(QuizLeaderboard).where(
                QuizLeaderboard.user_id == user.id,
                QuizLeaderboard.chat_id == chat_id,
                QuizLeaderboard.week_start == week,
            )
        )
        entry = result.scalar_one_or_none()
        if entry is not None:
            entry.streak = 0


async def get_leaderboard(
    chat_id: int,
    limit: int = 10,
    week: bool = True,
) -> list[QuizLeaderboard]:
    async with session_scope() as session:
        q = select(QuizLeaderboard).where(QuizLeaderboard.chat_id == chat_id)
        if week:
            q = q.where(QuizLeaderboard.week_start == _current_week_start())
        q = q.order_by(desc(QuizLeaderboard.points)).limit(limit)
        result = await session.execute(q)
        return list(result.scalars().all())


async def get_user_rank(
    telegram_id: int,
    chat_id: int,
) -> tuple[int, int, int]:
    """Return (rank, points, streak). rank 1-based; 0 = not found."""
    week = _current_week_start()
    async with session_scope() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return 0, 0, 0

        result = await session.execute(
            select(QuizLeaderboard).where(
                QuizLeaderboard.user_id == user.id,
                QuizLeaderboard.chat_id == chat_id,
                QuizLeaderboard.week_start == week,
            )
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            return 0, 0, 0

        result = await session.execute(
            select(func.count(QuizLeaderboard.id)).where(
                QuizLeaderboard.chat_id == chat_id,
                QuizLeaderboard.week_start == week,
                QuizLeaderboard.points > entry.points,
            )
        )
        above = result.scalar_one() or 0
        return above + 1, entry.points, entry.streak


async def get_chat_quiz_stats(chat_id: int) -> dict:
    week = _current_week_start()
    async with session_scope() as session:
        result = await session.execute(
            select(func.count(QuizLeaderboard.id)).where(
                QuizLeaderboard.chat_id == chat_id,
                QuizLeaderboard.week_start == week,
            )
        )
        players = result.scalar_one() or 0

        result = await session.execute(
            select(func.count(QuizLog.id)).where(QuizLog.chat_id == chat_id)
        )
        total_answers = result.scalar_one() or 0

        return {"players_this_week": players, "total_answers": total_answers}
