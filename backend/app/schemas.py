"""API 请求/响应 Pydantic 模型。"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


# ===== 模板 =====
class TemplateOut(BaseModel):
    model_config = {"from_attributes": True, "populate_by_name": True}

    id: int
    name: str
    category: str
    template_schema: dict[str, Any] = Field(
        validation_alias="schema_", serialization_alias="schema"
    )
    is_builtin: bool
    is_active: bool
    created_at: datetime


class TemplateCreate(BaseModel):
    name: str
    category: str
    template_schema: dict[str, Any] = Field(alias="schema")
    is_active: bool = True


# ===== 生成 =====
class KeyFact(BaseModel):
    name: str
    value: str


class Person(BaseModel):
    name: str
    title: str = ""


class GenerateRequest(BaseModel):
    title: str = ""
    eventDesc: str
    keyFacts: list[KeyFact] = Field(default_factory=list)
    people: list[Person] = Field(default_factory=list)
    audience: str = ""
    style: str = "正式"
    styles: list[str] = Field(default_factory=list)  # 一次生成多文风版本（含 style）
    template: str = "news_release"
    referenceMaterials: list[int | str] = Field(default_factory=list)


class FactCheckItem(BaseModel):
    claim: str
    status: str  # 一致/不一致/无法核实
    basis: str = ""
    suggestion: str = ""


class GenerateResponse(BaseModel):
    draft: str
    revisionSuggestions: list[str] = Field(default_factory=list)
    factCheckReport: list[FactCheckItem] = Field(default_factory=list)
    versionId: str
    sources: list[Any] = Field(default_factory=list)
    generatedAt: datetime
    model: str = ""
    riskFlags: list[str] = Field(default_factory=list)
    variants: list[dict[str, Any]] = Field(default_factory=list)  # [{style, content}] 多文风对比


# ===== 多轮修改 =====
class ReviseRequest(BaseModel):
    draftId: str
    instruction: str


class RevertRequest(BaseModel):
    targetId: str


class ReviseResponse(BaseModel):
    draft: str
    versionId: str
    version: int
    diffSummary: list[str] = Field(default_factory=list)
    generatedAt: datetime
    model: str = ""


# ===== 润色 =====
class PolishRequest(BaseModel):
    draftId: str | None = None
    text: str | None = None


class PolishChange(BaseModel):
    original: str
    revised: str
    reason: str


class PolishResponse(BaseModel):
    polished: str
    changes: list[PolishChange] = Field(default_factory=list)
    versionId: str | None = None  # 基于 draftId 润色时产生新版本
    generatedAt: datetime
    model: str = ""


# ===== 草稿详情 / 版本树 =====
class ElementOut(BaseModel):
    id: int
    name: str
    value: str
    verified_status: str
    source_ref: str

    model_config = {"from_attributes": True}


class DraftDetail(BaseModel):
    id: str
    title: str
    template_name: str
    style: str
    content: str
    version: int
    parent_id: str | None
    root_id: str | None
    status: str
    model: str
    revision_instruction: str = ""
    input_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    elements: list[ElementOut] = Field(default_factory=list)
    fact_checks: list[FactCheckItem] = Field(default_factory=list)


class VersionNode(BaseModel):
    id: str
    version: int
    parent_id: str | None
    title: str
    status: str
    revision_instruction: str = ""
    created_at: datetime
    children: list["VersionNode"] = Field(default_factory=list)


# ===== 导出 =====
class ExportRequest(BaseModel):
    draftId: str
    format: Literal["md", "docx", "pdf"] = "md"


class ExportResponse(BaseModel):
    file_path: str
    download_url: str
    format: str


# ===== 素材 =====
class MaterialOut(BaseModel):
    id: int
    filename: str
    content_type: str
    status: str
    text_length: int
    created_at: datetime


class MaterialDetail(MaterialOut):
    text_content: str = ""
