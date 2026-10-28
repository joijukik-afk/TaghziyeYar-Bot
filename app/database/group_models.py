"""مدل دیتابیس برای اعضای گروه‌ها (جهت تگ کردن)"""

from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, Integer, String, UniqueConstraint
from app.database.models import Base

class GroupMember(Base):
    __tablename__ = "group_members"
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)
    user_id = Column(BigInteger, index=True)
    first_name = Column(String(128))
    username = Column(String(64), nullable=True)
    last_seen = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (UniqueConstraint("chat_id", "user_id", name="uq_group_user"),)
