"""数据模型（SQLAlchemy 2.0）。

表：template / draft / draft_element / fact_check / export_log / reference_material / style_config
    / policy_document / policy_clause / qa_log / compliance_report
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Template(Base):
    __tablename__ = "template"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    schema_: Mapped[dict] = mapped_column("schema", JSON)  # 模板结构（sections/placeholders 等）
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Draft(Base):
    __tablename__ = "draft"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    template_id: Mapped[int | None] = mapped_column(ForeignKey("template.id"), nullable=True)
    template_name: Mapped[str] = mapped_column(String(128), default="")  # 冗余，防模板被删
    style: Mapped[str] = mapped_column(String(32), default="正式")
    content: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    root_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # 版本树根节点
    status: Mapped[str] = mapped_column(String(32), default="草稿")  # 草稿/审阅中/已发布
    model: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)  # 输入要素快照，保证可溯源
    revision_instruction: Mapped[str] = mapped_column(Text, default="")  # 生成本版本所用的修改指令
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    elements: Mapped[list["DraftElement"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )
    fact_checks: Mapped[list["FactCheck"]] = relationship(
        back_populates="draft", cascade="all, delete-orphan"
    )


class DraftElement(Base):
    __tablename__ = "draft_element"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("draft.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text, default="")
    verified_status: Mapped[str] = mapped_column(String(32), default="未校验")  # 一致/不一致/无法核实/未校验
    source_ref: Mapped[str] = mapped_column(String(512), default="")

    draft: Mapped[Draft] = relationship(back_populates="elements")


class FactCheck(Base):
    __tablename__ = "fact_check"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("draft.id"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))  # 一致/不一致/无法核实
    basis: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")

    draft: Mapped[Draft] = relationship(back_populates="fact_checks")


class ExportLog(Base):
    __tablename__ = "export_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    draft_id: Mapped[str] = mapped_column(String(64), index=True)
    format: Mapped[str] = mapped_column(String(16))
    file_path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ReferenceMaterial(Base):
    __tablename__ = "reference_material"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str] = mapped_column(String(128), default="")
    text_content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="已入库")  # 已入库/解析失败
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    chunks: Mapped[list["MaterialChunk"]] = relationship(
        back_populates="material", cascade="all, delete-orphan"
    )


class MaterialChunk(Base):
    __tablename__ = "material_chunk"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("reference_material.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list[float]] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    material: Mapped[ReferenceMaterial] = relationship(back_populates="chunks")


class StyleConfig(Base):
    __tablename__ = "style_config"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 单行配置：key="styles"，value 为完整文风配置 JSON（styles 数组 + channel_style_map）
    config_key: Mapped[str] = mapped_column(String(32), unique=True, index=True, default="styles")
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PolicyDocument(Base):
    """公开政策法规文档元数据。政策域由 Python 负责解析和索引，Java 只做网关与管理查询。"""

    __tablename__ = "policy_document"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), index=True)
    doc_number: Mapped[str] = mapped_column(String(128), default="", index=True)
    issuing_authority: Mapped[str] = mapped_column(String(256), default="")
    level: Mapped[str] = mapped_column(String(64), default="其他", index=True)
    publish_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="现行有效", index=True)
    industry_tags: Mapped[list] = mapped_column(JSON, default=list)
    source_url: Mapped[str] = mapped_column(String(1024), default="")
    file_path: Mapped[str] = mapped_column(String(512), default="")
    text_content: Mapped[str] = mapped_column(Text, default="")
    parse_status: Mapped[str] = mapped_column(String(32), default="已完成", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    clauses: Mapped[list["PolicyClause"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class PolicyClause(Base):
    """条款级索引单元，embedding 使用 JSON 保存，便于离线开发环境运行。"""

    __tablename__ = "policy_clause"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(ForeignKey("policy_document.id"), index=True)
    chapter_path: Mapped[str] = mapped_column(String(256), default="")
    article_no: Mapped[str] = mapped_column(String(64), default="", index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    page: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float]] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    document: Mapped[PolicyDocument] = relationship(back_populates="clauses")


class QALog(Base):
    __tablename__ = "qa_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(128), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ComplianceReport(Base):
    __tablename__ = "compliance_report"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_desc: Mapped[str] = mapped_column(Text)
    industry: Mapped[str] = mapped_column(String(128), default="", index=True)
    items: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SourceConfig(Base):
    """行业/竞品情报采集源。"""

    __tablename__ = "source_config"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    type: Mapped[str] = mapped_column(String(16), index=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    competitors: Mapped[list] = mapped_column(JSON, default=list)
    frequency: Mapped[str] = mapped_column(String(32), default="daily")
    status: Mapped[str] = mapped_column(String(32), default="enabled", index=True)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    tasks: Mapped[list["CollectionTaskLog"]] = relationship(back_populates="source")


class CollectedArticle(Base):
    __tablename__ = "collected_article"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source_config.id"), index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(2048), default="")
    author: Mapped[str] = mapped_column(String(256), default="")
    publish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="new", index=True)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class ArticleCluster(Base):
    __tablename__ = "article_cluster"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String(256), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    article_ids: Mapped[list] = mapped_column(JSON, default=list)
    report_count: Mapped[int] = mapped_column(Integer, default=0)
    time_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    time_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class IntelligenceReport(Base):
    __tablename__ = "intelligence_report"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256))
    period: Mapped[str] = mapped_column(String(64), index=True)
    topic_tags: Mapped[list] = mapped_column(JSON, default=list)
    items: Mapped[list] = mapped_column(JSON, default=list)
    trend: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    model: Mapped[str] = mapped_column(String(128), default="")
    risk_flags: Mapped[list] = mapped_column(JSON, default=list)


class CollectionTaskLog(Base):
    __tablename__ = "collection_task_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source_config.id"), index=True)
    celery_task_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    items_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    source: Mapped[SourceConfig] = relationship(back_populates="tasks")
