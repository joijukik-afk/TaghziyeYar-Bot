"""CRUD helpers — thin wrappers around the SQLAlchemy session."""

from datetime import date, timedelta, datetime, timezone
from sqlalchemy import desc, func, select, delete
from sqlalchemy.exc import IntegrityError
from app.database.models import (
    AuditLog, BannedUser, Group, Profile, SentImage, User, WeightLog, QuizHistory, SystemState, GeneratedCard, DailyLog
)
from app.database.quiz_models import QuizLeaderboard, QuizLog
from app.database.group_models import GroupMember
from app.database.session import session_scope


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def get_or_create_user(telegram_id: int, username: str | None, first_name: str | None, last_name: str | None) -> User:
    async with session_scope() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            try:
                user = User(telegram_id=telegram_id, username=username, first_name=first_name, last_name=last_name)
                session.add(user); await session.flush()
                session.add(Profile(user_id=user.id)); await session.flush()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(select(User).where(User.telegram_id == telegram_id))
                user = result.scalar_one()
        else:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
        return user


async def get_user_by_telegram_id(telegram_id: int) -> User | None:
    async with session_scope() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()


async def get_user_by_username(username: str) -> User | None:
    clean_username = username.lstrip('@')
    async with session_scope() as session:
        result = await session.execute(select(User).where(User.username.ilike(clean_username)))
        return result.scalar_one_or_none()


async def get_or_create_group(chat_id: int, title: str | None) -> Group:
    async with session_scope() as session:
        result = await session.execute(select(Group).where(Group.chat_id == chat_id))
        group = result.scalar_one_or_none()
        if group is None:
            group = Group(chat_id=chat_id, title=title); session.add(group)
        else:
            group.title = title; group.is_active = True
        await session.flush(); await session.refresh(group)
        return group


async def list_all_groups() -> list[Group]:
    async with session_scope() as session:
        result = await session.execute(select(Group).where(Group.is_active == True))
        return list(result.scalars().all())


async def deactivate_group(chat_id: int) -> None:
    async with session_scope() as session:
        result = await session.execute(select(Group).where(Group.chat_id == chat_id))
        group = result.scalar_one_or_none()
        if group is not None:
            group.is_active = False; await session.flush()


async def get_profile(user_id: int) -> Profile | None:
    async with session_scope() as session:
        result = await session.execute(select(Profile).where(Profile.user_id == user_id))
        return result.scalar_one_or_none()


async def update_profile(user_id: int, **fields) -> Profile | None:
    async with session_scope() as session:
        result = await session.execute(select(Profile).where(Profile.user_id == user_id))
        profile = result.scalar_one_or_none()
        if profile is None: return None
        
        for key, value in fields.items():
            if hasattr(profile, key):
                # 👈 لایه امنیتی: اگر setup_step عدد بود، به رشته تبدیل کن
                if key == "setup_step" and isinstance(value, int):
                    value = str(value)
                setattr(profile, key, value)
                
        await session.flush(); await session.refresh(profile)
        return profile


async def log_weight(user_id: int, weight_kg: float) -> WeightLog:
    async with session_scope() as session:
        entry = WeightLog(user_id=user_id, weight_kg=weight_kg)
        session.add(entry); await session.flush(); await session.refresh(entry)
        return entry


async def list_weights(user_id: int, limit: int = 30) -> list[WeightLog]:
    async with session_scope() as session:
        result = await session.execute(
            select(WeightLog).where(WeightLog.user_id == user_id).order_by(WeightLog.logged_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


async def audit(telegram_id: int | None, event: str, details: str | None = None) -> None:
    async with session_scope() as session:
        session.add(AuditLog(telegram_id=telegram_id, event=event, details=details))


async def image_already_sent(image_url: str) -> bool:
    async with session_scope() as session:
        result = await session.execute(select(SentImage).where(SentImage.image_url == image_url))
        return result.scalar_one_or_none() is not None


async def mark_image_sent(image_url: str, keyword: str = "") -> None:
    async with session_scope() as session:
        existing = await session.execute(select(SentImage).where(SentImage.image_url == image_url))
        if existing.scalar_one_or_none() is None:
            session.add(SentImage(image_url=image_url, keyword=keyword[:300])); await session.flush()


async def cleanup_old_data(days: int = 30) -> tuple[int, int]:
    cutoff = _utc_now() - timedelta(days=days)
    async with session_scope() as session:
        res_img = await session.execute(delete(SentImage).where(SentImage.sent_at < cutoff))
        res_quiz = await session.execute(delete(QuizLog).where(QuizLog.created_at < cutoff))
        await session.flush()
        return res_img.rowcount, res_quiz.rowcount


def _current_week_start() -> str:
    today = date.today()
    days_since_saturday = (today.weekday() - 5) % 7
    return (today - timedelta(days=days_since_saturday)).isoformat()


async def record_quiz_answer(telegram_id: int, display_name: str, chat_id: int, chat_title: str, points: int, elapsed_ms: int, question_text: str, position: int) -> None:
    week = _current_week_start()
    async with session_scope() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            try:
                user = User(telegram_id=telegram_id, first_name=display_name)
                session.add(user); await session.flush()
                session.add(Profile(user_id=user.id)); await session.flush()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(select(User).where(User.telegram_id == telegram_id))
                user = result.scalar_one()
        result = await session.execute(select(QuizLeaderboard).where(QuizLeaderboard.user_id == user.id, QuizLeaderboard.chat_id == chat_id, QuizLeaderboard.week_start == week))
        entry = result.scalar_one_or_none()
        if entry is None:
            entry = QuizLeaderboard(user_id=user.id, telegram_id=telegram_id, display_name=display_name, chat_id=chat_id, chat_title=chat_title, week_start=week, points=points, wins=1, total_games=1, correct_answers=1, streak=1, best_streak=1)
            session.add(entry)
        else:
            entry.points += points; entry.wins += 1; entry.total_games += 1; entry.correct_answers += 1; entry.streak += 1
            if entry.streak > entry.best_streak: entry.best_streak = entry.streak
            entry.display_name = display_name
        session.add(QuizLog(chat_id=chat_id, question=question_text[:500], user_telegram_id=telegram_id, user_name=display_name, points=points, elapsed_ms=elapsed_ms, position=position))
        await session.flush()


async def record_quiz_wrong(telegram_id: int, chat_id: int) -> None:
    week = _current_week_start()
    async with session_scope() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None: return
        result = await session.execute(select(QuizLeaderboard).where(QuizLeaderboard.user_id == user.id, QuizLeaderboard.chat_id == chat_id, QuizLeaderboard.week_start == week))
        entry = result.scalar_one_or_none()
        if entry is not None: entry.streak = 0


async def get_leaderboard(chat_id: int, limit: int = 10, week: bool = True) -> list[QuizLeaderboard]:
    async with session_scope() as session:
        q = select(QuizLeaderboard).where(QuizLeaderboard.chat_id == chat_id)
        if week: q = q.where(QuizLeaderboard.week_start == _current_week_start())
        q = q.order_by(desc(QuizLeaderboard.points)).limit(limit)
        return list((await session.execute(q)).scalars().all())


async def get_user_rank(telegram_id: int, chat_id: int) -> tuple[int, int, int]:
    week = _current_week_start()
    async with session_scope() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None: return 0, 0, 0
        result = await session.execute(select(QuizLeaderboard).where(QuizLeaderboard.user_id == user.id, QuizLeaderboard.chat_id == chat_id, QuizLeaderboard.week_start == week))
        entry = result.scalar_one_or_none()
        if entry is None: return 0, 0, 0
        result = await session.execute(select(func.count(QuizLeaderboard.id)).where(QuizLeaderboard.chat_id == chat_id, QuizLeaderboard.week_start == week, QuizLeaderboard.points > entry.points))
        return (result.scalar_one() or 0) + 1, entry.points, entry.streak


async def ban_user(telegram_id: int, reason: str = "نقض قوانین") -> None:
    async with session_scope() as session:
        result = await session.execute(select(BannedUser).where(BannedUser.telegram_id == telegram_id))
        if result.scalar_one_or_none() is None:
            session.add(BannedUser(telegram_id=telegram_id, reason=reason)); await session.flush()


async def unban_user(telegram_id: int) -> None:
    async with session_scope() as session:
        result = await session.execute(select(BannedUser).where(BannedUser.telegram_id == telegram_id))
        banned = result.scalar_one_or_none()
        if banned:
            await session.delete(banned); await session.flush()


async def is_user_banned(telegram_id: int) -> bool:
    async with session_scope() as session:
        result = await session.execute(select(BannedUser).where(BannedUser.telegram_id == telegram_id))
        return result.scalar_one_or_none() is not None


async def get_recent_quiz_questions(limit: int = 30) -> list[str]:
    async with session_scope() as session:
        result = await session.execute(select(QuizHistory.question_text).order_by(QuizHistory.id.desc()).limit(limit))
        return [row[0] for row in result.fetchall()]


async def save_quiz_question(question_text: str) -> None:
    async with session_scope() as session:
        result = await session.execute(select(QuizHistory).where(QuizHistory.question_text == question_text[:500]))
        if result.scalar_one_or_none() is None:
            session.add(QuizHistory(question_text=question_text[:500]))
            await session.flush()


async def get_last_post_time() -> float:
    async with session_scope() as session:
        result = await session.execute(select(SystemState).where(SystemState.key == "last_post_time"))
        state = result.scalar_one_or_none()
        return float(state.value) if state else 0.0


async def set_last_post_time(timestamp: float) -> None:
    async with session_scope() as session:
        result = await session.execute(select(SystemState).where(SystemState.key == "last_post_time"))
        state = result.scalar_one_or_none()
        if state:
            state.value = str(timestamp)
        else:
            session.add(SystemState(key="last_post_time", value=str(timestamp)))
        await session.flush()


async def check_and_mark_card_generated(telegram_id: int) -> bool:
    async with session_scope() as session:
        result = await session.execute(select(GeneratedCard).where(GeneratedCard.telegram_id == telegram_id))
        if result.scalar_one_or_none():
            return False
        try:
            session.add(GeneratedCard(telegram_id=telegram_id))
            await session.flush()
            return True
        except IntegrityError:
            await session.rollback()
            return False


async def get_dynamic_admins() -> list[int]:
    async with session_scope() as session:
        result = await session.execute(select(SystemState).where(SystemState.key == "dynamic_admins"))
        state = result.scalar_one_or_none()
        if state and state.value:
            try:
                return [int(x.strip()) for x in state.value.split(",") if x.strip()]
            except Exception:
                return []
        return []


async def add_dynamic_admin(telegram_id: int) -> None:
    async with session_scope() as session:
        result = await session.execute(select(SystemState).where(SystemState.key == "dynamic_admins"))
        state = result.scalar_one_or_none()
        admins = []
        if state and state.value:
            try: admins = [int(x.strip()) for x in state.value.split(",") if x.strip()]
            except Exception: pass
        if telegram_id not in admins:
            admins.append(telegram_id)
            if state:
                state.value = ",".join(map(str, admins))
            else:
                session.add(SystemState(key="dynamic_admins", value=",".join(map(str, admins))))
            await session.flush()


async def remove_dynamic_admin(telegram_id: int) -> None:
    async with session_scope() as session:
        result = await session.execute(select(SystemState).where(SystemState.key == "dynamic_admins"))
        state = result.scalar_one_or_none()
        if state and state.value:
            try:
                admins = [int(x.strip()) for x in state.value.split(",") if x.strip()]
                if telegram_id in admins:
                    admins.remove(telegram_id)
                    state.value = ",".join(map(str, admins))
                    await session.flush()
            except Exception: pass


async def save_group_member(chat_id: int, user_id: int, first_name: str, username: str | None) -> None:
    async with session_scope() as session:
        res = await session.execute(select(GroupMember).where((GroupMember.chat_id == chat_id) & (GroupMember.user_id == user_id)))
        member = res.scalar_one_or_none()
        now_utc = _utc_now()
        if member:
            member.first_name = first_name; member.username = username; member.last_seen = now_utc
        else:
            try:
                session.add(GroupMember(chat_id=chat_id, user_id=user_id, first_name=first_name, username=username, last_seen=now_utc))
                await session.flush()
            except IntegrityError:
                await session.rollback()


async def get_group_members(chat_id: int, limit: int = 20) -> list[GroupMember]:
    async with session_scope() as session:
        stmt = (
            select(GroupMember)
            .where(GroupMember.chat_id == chat_id)
            .where((GroupMember.username == None) | (~GroupMember.username.ilike('%bot%') & ~GroupMember.username.ilike('%_bot')))
            .order_by(desc(GroupMember.last_seen))
            .limit(limit)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())


async def cleanup_inactive_members(days: int = 90) -> int:
    cutoff = _utc_now() - timedelta(days=days)
    async with session_scope() as session:
        result = await session.execute(delete(GroupMember).where(GroupMember.last_seen < cutoff))
        await session.flush()
        return result.rowcount


async def add_water_intake(user_id: int, log_date: str, glasses: int) -> None:
    """ثبت آب برای امروز (اضافه به مقدار قبلی)"""
    async with session_scope() as session:
        result = await session.execute(
            select(DailyLog).where(DailyLog.user_id == user_id, DailyLog.log_date == log_date)
        )
        log = result.scalar_one_or_none()
        if log is None:
            session.add(DailyLog(user_id=user_id, log_date=log_date, water_glasses=glasses))
        else:
            log.water_glasses = (log.water_glasses or 0) + glasses
        await session.flush()


async def get_today_water(user_id: int, log_date: str) -> int:
    async with session_scope() as session:
        result = await session.execute(
            select(DailyLog).where(DailyLog.user_id == user_id, DailyLog.log_date == log_date)
        )
        log = result.scalar_one_or_none()
        return log.water_glasses if log else 0
