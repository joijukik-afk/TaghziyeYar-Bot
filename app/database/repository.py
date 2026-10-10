"""CRUD helpers — thin wrappers around the SQLAlchemy session."""

from datetime import datetime

from sqlalchemy import select

from app.database.models import (
    AuditLog,
    Group,
    Profile,
    User,
    WeightLog,
)
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
