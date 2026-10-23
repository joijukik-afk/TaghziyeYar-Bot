"""مدل دیتابیس برای آهنگ‌های ارسال شده (ضد تکرار)"""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from app.database.models import Base


class MusicTrack(Base):
    __tablename__ = "music_tracks"

    id = Column(Integer, primary_key=True)
    identifier = Column(String(255), unique=True, index=True)
    title = Column(String(512))
    artist = Column(String(255), default="Unknown")
    filename = Column(String(512), nullable=True)
    source = Column(String(64), default="multi_source")
    file_hash = Column(String(64), index=True, nullable=True)
    telegram_file_id = Column(String(255), nullable=True)
    is_sent = Column(Boolean, default=False, index=True)
    sent_at = Column(DateTime, nullable=True)
    discovered_at = Column(DateTime, default=datetime.utcnow)
