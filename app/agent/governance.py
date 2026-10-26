from __future__ import annotations

import re
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import IntEnum

from fastapi import HTTPException
from sqlalchemy.orm import Session


class DataLevel(IntEnum):
    public = 0
    internal = 1
    confidential = 2
    restricted = 3


@dataclass(frozen=True)
class Principal:
    user_id: str = ""
    tenant_id: str = ""
    department_id: str = ""
    permissions: frozenset[str] = frozenset()
    clearance: DataLevel = DataLevel.public
    public_only: bool = True
    # G7：租户治理角色（platform_admin / tenant_admin / member）；空串表示网关尚未下发角色
    # 的过渡期口径，见 app/agent/access.py。
    role: str = ""

    @property
    def authenticated(self):
        return bool(self.user_id and self.tenant_id)

    def require(self, permission: str):
        if not self.authenticated or permission not in self.permissions:
            raise HTTPException(403, f"{permission} permission required")
        if self.role:
            # G7：角色基线是硬上限。即使调用方绕过网关第一跳的权限收敛
            # （例如直接构造 Principal），也不能拿到角色职责之外的能力。
            # 回退开关打开时角色治理整体停用，这里必须一起停，否则"回退"只回退了一半。
            from .access import governance_enabled, role_permissions
            if governance_enabled() and permission not in role_permissions(self.role):
                raise HTTPException(403, f"{permission} is outside the {self.role} role baseline")

    def can_read(self, level: str, tenant_id="", department_id="", owner_id=""):
        classification = DataLevel[level]
        if classification == DataLevel.public:
            return True
        if self.public_only or not self.authenticated or self.clearance < classification:
            return False
        if not tenant_id or tenant_id != self.tenant_id:
            return False
        if department_id and department_id != self.department_id:
            return False
        return not owner_id or owner_id == self.user_id


principal_var: ContextVar[Principal] = ContextVar("security_principal", default=Principal())
data_level_var: ContextVar[DataLevel] = ContextVar("data_classification", default=DataLevel.public)


@contextmanager
def classified_data(level):
    level = DataLevel[level] if isinstance(level, str) else level
    token = data_level_var.set(max(level, data_level_var.get()))
    from .runtime import current_run
    if capture := current_run.get():
        capture.classification = max(capture.classification, data_level_var.get())
    try:
        yield
    finally:
        data_level_var.reset(token)

SECRET_KEYS = {
    "password", "token", "api_key", "apikey", "authorization", "x-internal-token",
    "access_token", "refresh_token", "secret", "client_secret", "llm_api_key",
    "embedding_api_key", "rerank_api_key", "cookie", "set-cookie",
}
PII_PATTERNS = [
    (r"(?<!\d)\d{17}[\dXx](?!\d)", "[ID_REDACTED]"),
    (r"(?<!\d)1[3-9]\d{9}(?!\d)", "[PHONE_REDACTED]"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL_REDACTED]"),
    (r"(?<!\d)\d{16,19}(?!\d)", "[ACCOUNT_REDACTED]"),
    (r"(?i)\bBearer\s+[A-Za-z0-9_.~-]+", "Bearer [REDACTED]"),
    (r"(?i)\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*[^\s,;]+", "[SECRET_REDACTED]"),
]


def redact(value):
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if str(k).lower() in SECRET_KEYS else redact(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for pattern, replacement in PII_PATTERNS:
            value = re.sub(pattern, replacement, value)
    return value


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_naive(value: datetime | None):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value and value.tzinfo else value


def audit(db: Session, action: str, resource: str, outcome="allowed", details=None, *, principal=None):
    from ..observability import trace_id_var
    from .platform_models import GovernanceAudit
    p = principal or principal_var.get()
    row = GovernanceAudit(
        tenant_id=p.tenant_id, department_id=p.department_id, user_id=p.user_id,
        trace_id=trace_id_var.get(), action=action, resource=resource[:256],
        outcome=outcome, details=redact(details or {}), created_at=utcnow(),
        expires_at=utcnow() + timedelta(days=90),
    )
    db.add(row)
    return row


def assert_external_model_allowed(*, binary=False):
    from .runtime import current_run
    capture = current_run.get()
    level = max(data_level_var.get(), capture.classification if capture else DataLevel.public)
    if level == DataLevel.restricted:
        raise HTTPException(403, "restricted data cannot be sent to an external model")
    if binary and level != DataLevel.public:
        raise HTTPException(403, "external image/audio parsing requires reviewed public data")


def model_messages(messages):
    """Remote providers never receive credentials or direct personal identifiers."""
    assert_external_model_allowed()
    return redact(messages)


def governed_get(db, model, key):
    """Recheck identity-map hits, which do not execute scoped SELECTs."""
    row = db.get(model, key)
    p = principal_var.get()
    if row and p.authenticated:
        level = getattr(row, "classification", "internal")
        if not p.can_read(level, row.tenant_id, row.department_id, getattr(row, "owner_id", "")):
            return None
        data_level_var.set(max(data_level_var.get(), DataLevel[level]))
    return row


def require_route_permission(path, method):
    """One permission vocabulary for direct HTTP routes and registered tools."""
    p = principal_var.get()
    groups = {
        "/api/policy": "policy", "/api/chat": "policy", "/api/compliance": "policy",
        "/api/drafts": "draft", "/api/exports": "draft", "/api/materials": "materials",
        "/api/templates": "templates", "/api/meeting/ai": "meeting",
        "/api/intelligence": "materials", "/api/opinion/ai": "opinion",
        "/api/sources": "materials", "/api/reports/intelligence": "materials",
        "/static/uploads": "materials", "/static/exports": "draft",
        # G7：agent 管理面同样在"网关第一跳"就按角色权限拦下，普通用户进不到端点内部。
        "/api/agent/knowledge": "knowledge",
        "/api/agent/flags": "platform",
        "/api/agent/costs": "platform",
        "/api/agent/model-routing": "platform",
        "/api/agent/governance": "platform",
        "/api/agent/tenants": "platform",
        "/api/agent/ltr": "platform",
    }
    for prefix, domain in groups.items():
        if path == prefix or path.startswith(prefix + "/"):
            permission = f"{domain}:read" if method in {"GET", "HEAD"} or domain in {"policy", "meeting"} else f"{domain}:write"
            if domain == "platform":
                # 治理面读（开关现状 / 成本报表 / 审计）需 agent:audit；写动作与租户治理需 agent:admin。
                permission = "agent:audit" if method in {"GET", "HEAD"} and not path.startswith("/api/agent/tenants") else "agent:admin"
            if domain == "draft":
                permission = "draft:write"
                if path == "/api/drafts" and method == "GET" or path.endswith("/review"):
                    permission = "draft:review"
                elif path.endswith("/verify"):
                    permission = "draft:verify"
            if domain == "policy" and ("/documents" in path or path.endswith("/reindex")) and method not in {"GET", "HEAD"}:
                permission = "knowledge:publish"
            if domain == "materials" and path.endswith("/reindex"):
                # 与职责映射对齐：重建索引 = "知识库：素材入库与重建索引"（materials.manage → materials:write）
                permission = "materials:write"
            if domain == "knowledge" and path.rsplit("/", 1)[-1] in {"publish", "cancel", "rollback"}:
                # 发布 / 取消 / 回滚按动作档位在路由级就拦，不在端点内才收紧
                permission = "knowledge:publish"
            if domain == "templates" and method in {"GET", "HEAD"}:
                permission = "policy:read"
            p.require(permission)
            return permission
    return ""


def authorize_download(db, path, resource=""):
    from pathlib import Path
    from ..models import Draft, ExportLog, ReferenceMaterial
    filename = path.rsplit("/", 1)[-1]
    if not filename or filename in {".", ".."} or "\\" in filename:
        raise HTTPException(404, "file not found")
    if resource:
        principal_var.get().require("opinion:read")
        match = re.fullmatch(r"opinion-report:([1-9]\d*)", resource)
        if not match or path not in {
            f"/static/uploads/opinion-report_{match[1]}.pdf",
            f"/static/uploads/opinion-report_{match[1]}.html",
        }:
            raise HTTPException(404, "file not found")
        return
    if path.startswith("/static/uploads/"):
        material_id = filename.split("_", 1)[0]
        row = db.query(ReferenceMaterial).filter_by(id=int(material_id)).first() if material_id.isdigit() else None
        allowed = row and filename == f"{row.id}_{row.filename}"
    else:
        allowed = any(Path(row.file_path).name == filename
                      for row in db.query(ExportLog).join(Draft).all())
    if not allowed:
        raise HTTPException(404, "file not found")


def install_data_isolation():
    from sqlalchemy import event, false, or_, select
    from sqlalchemy.orm import with_loader_criteria
    from ..models import Draft, ReferenceMaterial, DraftElement, FactCheck, ExportLog, MaterialChunk
    from .models import DraftEvidence, DraftReview

    @event.listens_for(Session, "do_orm_execute")
    def scoped_query(state):
        p = principal_var.get()
        # Internal workers and offline migrations have no interactive principal.
        if not p.authenticated or not state.is_select:
            return
        levels = [level.name for level in DataLevel if level <= p.clearance]
        for model in (Draft, ReferenceMaterial):
            private = (
                (model.tenant_id == p.tenant_id)
                & model.classification.in_(levels)
                & or_(model.department_id == "", model.department_id == p.department_id)
            )
            if model is ReferenceMaterial:
                private = private & or_(model.owner_id == "", model.owner_id == p.user_id)
            if p.public_only:
                private = false()
            criteria = (model.classification == "public") | private
            state.statement = state.statement.options(with_loader_criteria(model, criteria, include_aliases=True))
            children = ((DraftElement, FactCheck, ExportLog, DraftEvidence, DraftReview)
                        if model is Draft else (MaterialChunk,))
            for child in children:
                parent_id = child.draft_id if model is Draft else child.material_id
                state.statement = state.statement.options(with_loader_criteria(
                    child, parent_id.in_(select(model.id).where(criteria)), include_aliases=True,
                ))

    @event.listens_for(Session, "before_flush")
    def scope_new_data(db, flush_context, instances):
        p = principal_var.get()
        if not p.authenticated:
            return
        for row in db.new:
            if isinstance(row, (Draft, ReferenceMaterial)):
                row.tenant_id = p.tenant_id
                row.department_id = p.department_id
                row.classification = row.classification or "internal"
                if isinstance(row, Draft):
                    row.classification = max(DataLevel[row.classification], data_level_var.get(), DataLevel.internal).name
                if p.public_only and row.classification != "public":
                    raise HTTPException(403, "public-only task cannot store private enterprise data")
                if DataLevel[row.classification] > p.clearance:
                    raise HTTPException(403, "classification exceeds trusted clearance")
                if isinstance(row, ReferenceMaterial):
                    row.owner_id = p.user_id
