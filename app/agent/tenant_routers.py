"""G7 · 租户治理端点：平台管理员"管租户"的可验证落点。

- `GET /api/agent/tenants`：租户治理概览，需 `agent:admin`（平台管理员）。
  **只回治理元数据**（命名空间、版本数、审计条数），永不回知识正文——
  跨租户读内容这件事对任何角色都不开放，内容级仍由 `Principal.can_read` 决定。
- `GET /api/agent/roles`：三角色职责映射（谁管什么、要什么权限、卡在哪三道门），
  任意受信身份可读：治理规则本身应当是透明的，不透明的是数据。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..security import require_internal_token
from .access import (
    ROLE_HEADER, TARGET_TENANT_HEADER, normalize_role, require_tenant_scope,
    responsibility_matrix, role_spec,
)
from .governance import principal_var
from .platform_models import GovernanceAudit, KnowledgeRelease

router = APIRouter(dependencies=[Depends(require_internal_token)])

ALL_TENANTS = "all"


@router.get("/roles")
def role_governance() -> dict:
    """三角色职责映射 + 当前身份落在哪个角色上（受信身份即可读）。"""
    principal = principal_var.get()
    if not principal.authenticated:
        raise HTTPException(403, "trusted tenant identity required")
    name = normalize_role(principal.role)
    spec = role_spec(name)
    matrix = responsibility_matrix()
    matrix["current"] = {
        "role": name or "legacy",
        "title": spec.title if spec else "过渡期身份（网关未下发角色头）",
        "scope": spec.scope if spec else "",
        "permissions": sorted(principal.permissions),
        "tenantId": principal.tenant_id,
    }
    return matrix


@router.get("/tenants")
def tenant_governance_overview(
    target: str = Query(default="", description="留空=本租户，all=全平台（仅平台管理员），或指定租户"),
    x_target_tenant: str = Header(default="", alias="X-Target-Tenant"),
    db: Session = Depends(get_db),
) -> dict:
    """租户治理概览：平台管理员看得到租户地毯，但看不到租户内容。"""
    principal = principal_var.get()
    principal.require("agent:admin")
    requested = (target or x_target_tenant or "").strip()
    scope = require_tenant_scope(principal, requested)
    wildcard = scope == ALL_TENANTS and normalize_role(principal.role) == "platform_admin"

    release_counts = dict(
        db.query(KnowledgeRelease.namespace, func.count(KnowledgeRelease.id))
        .group_by(KnowledgeRelease.namespace).all()
    )
    audit_counts = dict(
        db.query(GovernanceAudit.tenant_id, func.count(GovernanceAudit.id))
        .group_by(GovernanceAudit.tenant_id).all()
    )
    tenants: dict[str, dict] = {}
    for namespace, count in release_counts.items():
        parts = namespace.split(":")
        if len(parts) < 3 or parts[0] != "tenant":
            continue
        entry = tenants.setdefault(parts[1], {"knowledgeNamespaces": [], "knowledgeReleases": 0,
                                              "auditRecords": 0, "crossTenantVisible": False})
        entry["knowledgeNamespaces"].append(namespace)
        entry["knowledgeReleases"] += int(count)
    for tenant_id, count in audit_counts.items():
        if not tenant_id:
            continue
        entry = tenants.setdefault(tenant_id, {"knowledgeNamespaces": [], "knowledgeReleases": 0,
                                               "auditRecords": 0, "crossTenantVisible": False})
        entry["auditRecords"] += int(count)

    rows = []
    for tenant_id in sorted(tenants):
        if not wildcard and tenant_id != scope:
            continue
        entry = tenants[tenant_id]
        rows.append({
            "tenantId": tenant_id,
            "knowledgeNamespaces": sorted(entry["knowledgeNamespaces"]),
            "knowledgeReleases": entry["knowledgeReleases"],
            "auditRecords": entry["auditRecords"],
            "crossTenantVisible": tenant_id != principal.tenant_id,
        })
    return {
        "scope": scope,
        "wildcard": wildcard,
        "metadataOnly": True,
        "note": (
            "本端点只回治理元数据（命名空间 / 版本数 / 审计条数）；"
            "跨租户知识正文与审计明细仍按租户与密级过滤，平台管理员也不例外。"
        ),
        "roleHeader": ROLE_HEADER,
        "targetTenantHeader": TARGET_TENANT_HEADER,
        "tenants": rows,
    }