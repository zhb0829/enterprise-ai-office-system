"""数据模型（SQLAlchemy 2.0）。

表：template / draft / draft_element / fact_check / export_log / reference_material
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
