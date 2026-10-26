"""知识图谱存储表（G1）。

起步用 networkx + 关系表：图在内存里算，事实落在关系表里，可重建、可审计，将来换
Neo4j 只需替换 `store` / `traverse` 的实现，抽取与对齐不受影响。

治理口径与现有业务表一致但仍需显式过滤：`install_data_isolation` 只覆盖
`Draft` / `ReferenceMaterial` 及其子表，图数据必须由检索侧再走一次
`Principal.can_read`，不假设第二道防线存在。
"""
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class KGEntity(Base):
    """图节点：一个对齐后的规范实体。"""

    __tablename__ = "kg_entity"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    department_id: Mapped[str] = mapped_column(String(64), default="")
    classification: Mapped[str] = mapped_column(String(16), default="internal", index=True)
    name: Mapped[str] = mapped_column(String(256))
    norm_key: Mapped[str] = mapped_column(String(256))
    entity_type: Mapped[str] = mapped_column(String(64), index=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    source_refs: Mapped[list] = mapped_column(JSON, default=list)
    merge_log: Mapped[list] = mapped_column(JSON, default=list)
    degree: Mapped[int] = mapped_column(Integer, default=0)
    community_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_kg_entity_scope", "tenant_id", "entity_type", "norm_key"),)


class KGRelation(Base):
    """图边：一条白名单内的关系，带来源与证据，便于回溯到原文条款。"""

    __tablename__ = "kg_relation"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    department_id: Mapped[str] = mapped_column(String(64), default="")
    classification: Mapped[str] = mapped_column(String(16), default="internal", index=True)
    relation_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_key: Mapped[str] = mapped_column(String(160), default="", index=True)
    head_id: Mapped[int] = mapped_column(ForeignKey("kg_entity.id"), index=True)
    tail_id: Mapped[int] = mapped_column(ForeignKey("kg_entity.id"), index=True)
    relation_type: Mapped[str] = mapped_column(String(64), index=True)
    evidence: Mapped[str] = mapped_column(Text, default="")
    source_ref: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KGCommunity(Base):
    """社区摘要：全局性问题的入口，避免每次都钻底层节点。"""

    __tablename__ = "kg_community"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="default", index=True)
    classification: Mapped[str] = mapped_column(String(16), default="internal", index=True)
    domain: Mapped[str] = mapped_column(String(32), default="policy", index=True)
    level: Mapped[int] = mapped_column(Integer, default=0)
    signature: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    entity_ids: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    source: Mapped[str] = mapped_column(String(32), default="rule")  # rule / llm
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
