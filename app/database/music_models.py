"""مدل دیتابیس آهنگ‌های ارسال‌شده KOMA

جدول اصلی برای جلوگیری از ارسال تکراری و نگه‌داری file_id تلگرام.
سازگار با music_service.py نسخه 2.0
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MusicTrack(Base):
    __tablename__ = "music_tracks"

    # --- کلید اصلی ---
    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- شناسه یکتای آهنگ در منبع (SoundCloud ID یا MD5 لینک) ---
    identifier = Column(String(128), nullable=False, unique=True, index=True)

    # --- اطلاعات توصیفی ---
    title = Column(String(512), nullable=False, default="Unknown")
    artist = Column(String(512), nullable=False, default="Unknown Artist")
    filename = Column(String(512), nullable=True, default="")

    # --- یکتایی محتوا ---
    file_hash = Column(String(64), nullable=True, index=True)

    # --- ارجاع تلگرام ---
    telegram_file_id = Column(String(512), nullable=True)

    # --- وضعیت ارسال ---
    is_sent = Column(Boolean, nullable=False, default=False, index=True)
    sent_at = Column(DateTime(timezone=True), nullable=True, index=True)

    # --- زمان ایجاد رکورد ---
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=func.now(),
    )

    # --- محدودیت‌ها و ایندکس‌ها ---
    __table_args__ = (
        # جلوگیری از ثبت دوباره‌ی همان فایل هش (اختیاری - اگر null پذیر باشد مشکلی ندارد)
        UniqueConstraint("file_hash", name="uq_music_tracks_file_hash"),
        # کوئری سریع برای «آخرین ارسال‌ها»
        Index("ix_music_sent_recent", "is_sent", "sent_at"),
        # کوئری سریع برای جستجوی آرتیست
        Index("ix_music_artist_norm", "artist"),
    )

    # --- نمایش خوانا برای دیباگ ---
    def __repr__(self) -> str:
        return (
            f"<MusicTrack id={self.id} identifier={self.identifier!r} "
            f"title={self.title!r} artist={self.artist!r} "
            f"is_sent={self.is_sent}>"
        )
