"""会议模块的 Python 独占向量索引表。"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class MeetingKnowledgeIndex(Base):
    __tablename__ = "meeting_knowledge_index"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conference_id: Mapped[int] = mapped_column(Integer, index=True)
    card_type: Mapped[str] = mapped_column(String(32), default="", index=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    source_ref: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
