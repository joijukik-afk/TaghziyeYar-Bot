"""Database model for saving user state (persona, chat history)."""

from datetime import datetime, timezone
from sqlalchemy import BigInteger, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserState(Base):
    __tablename__ = "user_states"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.telegram_id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    persona_key: Mapped[str] = mapped_column(String(50), default="default")
    chat_history_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now,
    )
