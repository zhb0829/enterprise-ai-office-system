"""舆情分析 - Python 独占 AI 记录表。

这些表只保存 Python 侧的 AI 任务执行记录与模型调用记录，
不保存任何 Java 业务事实（文章/事件/告警由 Java 服务独占）。
"""
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class OpinionAiRun(Base):
    """AI 分析任务运行记录。"""

    __tablename__ = "opinion_ai_run"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    task_id: Mapped[int] = mapped_column(Integer, index=True, default=0)
    article_id: Mapped[int] = mapped_column(Integer, index=True, default=0)
    monitor_id: Mapped[int] = mapped_column(Integer, index=True, default=0)
    stage: Mapped[str] = mapped_column(String(32), default="collect")  # collect / analyze
    status: Mapped[str] = mapped_column(String(16), default="queued")
    source_type: Mapped[str] = mapped_column(String(16), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OpinionAiModelCall(Base):
    """DeepSeek / 轻量模型调用记录（脱敏后）。"""

    __tablename__ = "opinion_ai_model_call"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    stage: Mapped[str] = mapped_column(String(32), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    provider: Mapped[str] = mapped_column(String(32), default="rule")  # rule / deepseek / embedding
    prompt_version: Mapped[str] = mapped_column(String(64), default="")
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(default=False)
    sent_hash: Mapped[str] = mapped_column(String(64), default="")  # 脱敏输入摘要哈希
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OpinionCaseChunk(Base):
    """历史应对案例切片（Python 独占 RAG 索引，向量以 JSON 保存便于离线运行）。"""

    __tablename__ = "opinion_case_chunk"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(Integer, index=True, default=0)
    case_title: Mapped[str] = mapped_column(String(256), default="")
    event_type: Mapped[str] = mapped_column(String(128), default="", index=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="")
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
