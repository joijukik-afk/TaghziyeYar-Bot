"""Repository for managing user state in the database."""

import json
import logging
from typing import Optional
from sqlalchemy import select
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
        logger.error(f"Error loading user state: {e}")
        return None

async def save_user_state(user_id: int, persona_key: str, chat_history: list) -> None:
    """ذخیره وضعیت و حافظه کاربر در دیتابیس"""
    try:
        async with session_scope() as session:
            result = await session.execute(select(UserState).where(UserState.user_id == user_id))
            state = result.scalar_one_or_none()
            history_json = json.dumps(chat_history, ensure_ascii=False)
            
            if state:
                state.persona_key = persona_key
                state.chat_history_json = history_json
            else:
                new_state = UserState(user_id=user_id, persona_key=persona_key, chat_history_json=history_json)
                session.add(new_state)
            await session.flush()
    except Exception as e:
        logger.error(f"Error saving user state: {e}")
