"""مدل دیتابیس برای کش آهنگ‌های KOMA."""

from datetime import datetime, timezone
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Integer, String, Text, Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.database.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MusicTrack(Base):
    """ذخیره آهنگ‌های ارسال شده برای جلوگیری از تکرار."""

    __tablename__ = "music_tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(String(255), unique=True, index=True)  # ID یکتا (ساندکلود/یوتیوب/آدیوس)
    title: Mapped[str] = mapped_column(String(255), default="Unknown")
    artist: Mapped[str] = mapped_column(String(255), default="Unknown Artist")
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA256
    telegram_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # file_id تلگرام برای کش
    is_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        # 👈 ایندکس برای کوئری‌های کش (file_id != '' AND is_sent = TRUE)
        Index('ix_music_tracks_sent_fileid', 'is_sent', 'telegram_file_id'),
    )
