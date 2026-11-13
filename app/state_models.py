"""Database model for saving user state (persona, chat history)."""

from sqlalchemy import BigInteger, String, Text, Column
from app.database.session import Base

class UserState(Base):
    __tablename__ = "user_states"

    user_id = Column(BigInteger, primary_key=True, index=True)
    persona_key = Column(String(50), default="default")
    chat_history_json = Column(Text, default="[]") # حافظه چت به صورت JSON
