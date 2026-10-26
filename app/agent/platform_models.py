from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .governance import utcnow


class MemoryRecord(Base):
    __tablename__ = "agent_memory"
    __table_args__ = (UniqueConstraint("tenant_id", "department_id", "user_id", "scope", "session_id", "kind", "key", name="uq_agent_memory_scope_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    department_id: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    scope: Mapped[str] = mapped_column(String(16), default="user")
    session_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    kind: Mapped[str] = mapped_column(String(16))
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    classification: Mapped[str] = mapped_column(String(16), default="internal")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class GovernanceAudit(Base):
    __tablename__ = "governance_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    department_id: Mapped[str] = mapped_column(String(64), default="")
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    action: Mapped[str] = mapped_column(String(128))
    resource: Mapped[str] = mapped_column(String(256))
    outcome: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class KnowledgeRelease(Base):
    __tablename__ = "knowledge_release"
    __table_args__ = (UniqueConstraint("namespace", "version", name="uq_knowledge_namespace_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="staged")
    effective_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    manifest_hash: Mapped[str] = mapped_column(String(64))
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class KnowledgeHead(Base):
    __tablename__ = "knowledge_head"

    namespace: Mapped[str] = mapped_column(String(128), primary_key=True)
    release_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    next_version: Mapped[int] = mapped_column(Integer, default=1)


class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entry"

    release_id: Mapped[str] = mapped_column(ForeignKey("knowledge_release.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    chunks: Mapped[list] = mapped_column(JSON, default=list)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    classification: Mapped[str] = mapped_column(String(16), default="public")
    tenant_id: Mapped[str] = mapped_column(String(64), default="")
    department_id: Mapped[str] = mapped_column(String(64), default="")
    owner_id: Mapped[str] = mapped_column(String(64), default="")
    effective_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RankingModelRecord(Base):
    """G9：一个 LTR 排序模型版本。权重与指标全部落库，激活 / 退役可追溯、可回滚。"""

    __tablename__ = "ranking_model"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 版本号（由权重摘要生成）
    domain: Mapped[str] = mapped_column(String(32), default="policy", index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), default="shadow", index=True)
    features: Mapped[list] = mapped_column(JSON, default=list)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    bias: Mapped[float] = mapped_column(Float, default=0.0)
    samples: Mapped[int] = mapped_column(Integer, default=0)
    positives: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    dataset_digest: Mapped[str] = mapped_column(String(64), default="")
    notes: Mapped[str] = mapped_column(String(500), default="")
    trained_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
