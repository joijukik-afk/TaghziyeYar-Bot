"""Repository for managing user state in the database."""

import json
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database.session import session_scope
from app.database.state_models import UserState

logger = logging.getLogger(__name__)


async def get_user_state(user_id: int) -> Optional[UserState]:
    """دریافت وضعیت کاربر از دیتابیس"""
    try:
        async with session_scope() as session:
            result = await session.execute(select(UserState).where(UserState.user_id == user_id))
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error loading user state for {user_id}: {e}", exc_info=True)
        return None


async def save_user_state(user_id: int, persona_key: str, chat_history: list[dict]) -> None:
    """ذخیره وضعیت و حافظه کاربر در دیتابیس (با مدیریت همزمانی)"""
    history_json = json.dumps(chat_history, ensure_ascii=False)

    try:
        async with session_scope() as session:
            result = await session.execute(select(UserState).where(UserState.user_id == user_id))
            state = result.scalar_one_or_none()

            if state:
                state.persona_key = persona_key
                state.chat_history_json = history_json
            else:
                new_state = UserState(
                    user_id=user_id,
                    persona_key=persona_key,
                    chat_history_json=history_json,
                )
                session.add(new_state)

            await session.flush()

    except IntegrityError:
        # 👈 Race Condition: اگر همزمان دو تسک سعی در ساخت State جدید داشتند
        logger.warning(f"Race condition detected for user_state {user_id}. Retrying as update...")
        await _force_update_user_state(user_id, persona_key, history_json)
    except Exception as e:
        logger.error(f"Error saving user state for {user_id}: {e}", exc_info=True)


async def _force_update_user_state(user_id: int, persona_key: str, history_json: str) -> None:
    """تابع کمکی برای آپدیت اجباری در صورت بروز خطای همزمانی"""
    try:
        async with session_scope() as session:
            result = await session.execute(select(UserState).where(UserState.user_id == user_id))
            state = result.scalar_one_or_none()
            if state:
                state.persona_key = persona_key
                state.chat_history_json = history_json
                await session.flush()
    except Exception as e:
        logger.error(f"Critical error during force update for {user_id}: {e}", exc_info=True)
