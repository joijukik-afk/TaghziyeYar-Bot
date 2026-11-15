"""مدل دیتابیس برای اعضای گروه‌ها (جهت تگ کردن)"""

from datetime import datetime, timezone
from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.database.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GroupMember(Base):
    __tablename__ = "group_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    first_name: Mapped[str] = mapped_column(String(128))
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_group_user"),
        Index('ix_group_members_chat_lastseen', 'chat_id', 'last_seen'),
    )
