"""API 请求/响应 Pydantic 模型。"""
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _to_utc(value: datetime | None) -> datetime | None:
    """数据库列无时区（timestamp without time zone，实际存 UTC），统一补 UTC 时区，
    保证序列化带时区，前端按本地时间显示。"""
    if value is None:
        return value
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class TimestampedModel(BaseModel):
    @field_validator("created_at", "generatedAt", mode="before", check_fields=False)
    @classmethod
    def _normalize_datetime(cls, value):
        if isinstance(value, datetime):
            return _to_utc(value)
        return value


# ===== 模板 =====
class TemplateOut(TimestampedModel):
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


class GenerateResponse(TimestampedModel):
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


class EditRequest(BaseModel):
    content: str


class RevertRequest(BaseModel):
    targetId: str


class StatusUpdateRequest(BaseModel):
    status: Literal["草稿", "审阅", "发布"]


class ReviseResponse(TimestampedModel):
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


class PolishResponse(TimestampedModel):
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


class DraftDetail(TimestampedModel):
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


class VersionNode(TimestampedModel):
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


class ExportLogOut(TimestampedModel):
    model_config = {"from_attributes": True}

    id: int
    draft_id: str
    format: str
    file_path: str
    download_url: str = ""
    created_at: datetime


# ===== 素材 =====
class MaterialOut(TimestampedModel):
    id: int
    filename: str
    content_type: str
    status: str
    text_length: int
    created_at: datetime


class MaterialDetail(MaterialOut):
    text_content: str = ""


class MaterialChunkOut(TimestampedModel):
    model_config = {"from_attributes": True}

    id: int
    material_id: int
    filename: str = ""
    chunk_index: int
    text: str
    score: float = 0
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
