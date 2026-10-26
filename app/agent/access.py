"""G7 · 三角色租户治理分工：平台管理员（管租户）/ 租户管理员（管知识库）/ 普通用户（只提问）。

设计口径
--------

- **角色是"职责"，不是"第二套权限"**：现有四级密级（`DataLevel`）+ 细粒度权限集合 + 部门 + 属主
  不变，本模块只在其上补 角色 → 权限基线 / 租户范围 / 职责能力 的映射，避免两套授权模型互相打架。
- **只收缩，不放大**：声明角色后，有效权限 = 角色基线 ∩ 网关声明的权限集合。客户端伪造
  `X-User-Permissions` 提不了权（Java 网关剥离伪造头是第一道，这里是第二道）；即使有人绕过网关解析
  直接构造 `Principal`，`Principal.require` 也会用角色基线上限再拦一次（纵深防御）。
- **未声明角色保持既有行为**：Java 网关尚未下发 `X-User-Role` 的过渡期不收紧（`role == ""` 即
  legacy），一旦下发立即生效；`settings.tenant_role_governance_enabled` 可整体回退到过渡期口径。
- **三条硬边界**（验收用例围绕它们，见 `tests/test_g7_roles.py`）：
  1. 普通用户（member）不能做任何写 / 发布 / 审计动作 —— 只提问；
  2. 租户管理员不能操作平台级开关与跨租户治理 —— `agent:admin` 只属平台管理员；
  3. 跨租户只放行"治理元数据"，**任何角色都不能跨租户读内容**，内容级仍走 `Principal.can_read`。
- **职责可核对**：`CAPABILITY_PERMISSIONS` 把每条职责映射到它需要的权限，`responsibility_matrix()`
  对外导出，测试逐条校验：不允许"职责写了没有权限支撑"，也不允许"权限给了不对应任何职责"。

三个强制执行点（"从网关第一跳校验到检索末条 filter 全程贯通"）：

| 位置 | 代码 | 作用 |
|---|---|---|
| 网关第一跳 | `app/observability.py` 中间件调用 `harden_principal` | 未知角色 / 缺租户身份直接 403；权限按角色基线收敛 |
| 路由级 | `app/agent/governance.py::require_route_permission` | 管理面路径在进业务前按角色权限拦截 |
| 检索末条 | `filter_visible(...)`（`app/agent/knowledge.py`、`app/services/policy.py`） | 结果出站前逐条复核租户 / 密级 / 部门 / 属主，并记拒绝条数 |
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Iterable

from fastapi import HTTPException

from ..config import settings
from .governance import DataLevel, Principal

ROLE_HEADER = "x-user-role"
TARGET_TENANT_HEADER = "x-target-tenant"

PLATFORM_ADMIN = "platform_admin"
TENANT_ADMIN = "tenant_admin"
MEMBER = "member"

SCOPE_PLATFORM = "platform"
SCOPE_TENANT = "tenant"
SCOPE_SELF = "self"

# 职责 →（说明, 需要的权限）。职责是给人看的，权限是给代码判的，两者必须一一对得上。
CAPABILITY_PERMISSIONS: dict[str, tuple[str, str]] = {
    "tenant.provision": ("平台治理：租户开通 / 停用", "agent:admin"),
    "tenant.audit": ("平台治理：跨租户审计查看", "agent:admin"),
    "flag.operate": ("平台治理：运行时降级开关热切换", "agent:admin"),
    "knowledge.stage": ("知识库：暂存知识版本", "knowledge:write"),
    "knowledge.publish": ("知识库：发布 / 回滚版本", "knowledge:publish"),
    "knowledge.read": ("知识库：查看命名空间与快照", "knowledge:read"),
    "materials.manage": ("知识库：素材入库与重建索引", "materials:write"),
    "draft.write": ("办公：稿件撰写", "draft:write"),
    "draft.review": ("办公：稿件复核", "draft:review"),
    "draft.verify": ("办公：稿件事实核查", "draft:verify"),
    "templates.manage": ("办公：稿件模板维护", "templates:write"),
    "opinion.read": ("业务：舆情记录只读", "opinion:read"),
    "meeting.read": ("业务：会议公开信息只读", "meeting:read"),
    "audit.read": ("治理：查看本租户审计", "agent:audit"),
    "memory.share.tenant": ("治理：维护租户共享文风", "memory:tenant:write"),
    "memory.share.department": ("治理：维护部门共享文风", "memory:department:write"),
    "platform.status.read": ("治理：只读查看平台开关 / 路由 / 排序模型现状", "agent:audit"),
    "policy.ask": ("业务：政策问答（只读）", "policy:read"),
    "materials.search": ("业务：素材检索（只读）", "materials:read"),
    "memory.self": ("业务：读自己的偏好与会话记忆", "memory:read"),
    "memory.self.write": ("业务：写自己的偏好与会话记忆", "memory:write"),
}

MEMBER_PERMISSIONS = frozenset({
    "policy:read", "materials:read", "meeting:read", "memory:read", "memory:write",
})
TENANT_ADMIN_PERMISSIONS = MEMBER_PERMISSIONS | {
    "knowledge:read", "knowledge:write", "knowledge:publish",
    "materials:write", "draft:write", "draft:review", "draft:verify", "templates:write",
    "opinion:read", "agent:audit", "memory:department:write", "memory:tenant:write",
}
# 平台管理员 = 租户管理员 ∪ 平台治理权限（能力是超集，但三条硬边界不放松：
# 普通用户仍不能越权写，平台管理员仍不能跨租户读内容）。
PLATFORM_ADMIN_PERMISSIONS = TENANT_ADMIN_PERMISSIONS | {"agent:admin"}


@dataclass(frozen=True)
class RoleSpec:
    name: str
    title: str
    scope: str
    permissions: frozenset[str]
    responsibilities: tuple[str, ...]
    boundary: str


ROLES: dict[str, RoleSpec] = {
    PLATFORM_ADMIN: RoleSpec(
        PLATFORM_ADMIN, "平台管理员", SCOPE_PLATFORM, frozenset(PLATFORM_ADMIN_PERMISSIONS),
        ("tenant.provision", "tenant.audit", "flag.operate", "knowledge.stage", "knowledge.publish",
         "knowledge.read", "materials.manage", "draft.write", "draft.review", "draft.verify",
         "templates.manage", "opinion.read", "meeting.read", "audit.read", "platform.status.read",
         "memory.share.tenant", "memory.share.department",
         "policy.ask", "materials.search", "memory.self", "memory.self.write"),
        "管租户：可治理全部租户，但跨租户只能看治理元数据，读内容仍受租户与密级限制。",
    ),
    TENANT_ADMIN: RoleSpec(
        TENANT_ADMIN, "租户管理员", SCOPE_TENANT, frozenset(TENANT_ADMIN_PERMISSIONS),
        ("knowledge.stage", "knowledge.publish", "knowledge.read", "materials.manage",
         "draft.write", "draft.review", "draft.verify", "templates.manage", "opinion.read",
         "meeting.read", "audit.read", "platform.status.read",
         "memory.share.tenant", "memory.share.department",
         "policy.ask", "materials.search", "memory.self", "memory.self.write"),
        "管知识库：素材/知识域按租户隔离，只在本租户内生效；政策域是全局公共法规库，"
        "写入对所有租户可见，租户私有内容必须走素材域。平台级开关与跨租户治理不可用。",
    ),
    MEMBER: RoleSpec(
        MEMBER, "普通用户", SCOPE_SELF, frozenset(MEMBER_PERMISSIONS),
        ("policy.ask", "materials.search", "meeting.read", "memory.self", "memory.self.write"),
        "只提问：只读检索与自己的记忆，任何写 / 发布 / 审计动作都被拒绝。",
    ),
}


def normalize_role(value: str) -> str:
    return (value or "").strip().lower()[:32]


def role_spec(name: str) -> RoleSpec | None:
    return ROLES.get(normalize_role(name))


def role_permissions(name: str) -> frozenset[str]:
    """角色权限基线；未知角色一律拒绝（不回落成"没有角色所以不管"）。"""
    spec = role_spec(name)
    if spec is None:
        raise HTTPException(403, f"unknown tenant role: {normalize_role(name) or '(empty)'}")
    return spec.permissions


def governance_enabled() -> bool:
    return bool(settings.tenant_role_governance_enabled)


def effective_permissions(role: str, declared: Iterable[str]) -> frozenset[str]:
    """声明角色后的有效权限：角色基线 ∩ 网关声明。

    `declared` 为空表示网关只下发了角色（过渡期配置），此时用角色基线；
    一旦声明了权限集合，就只能收窄、不能越过基线。
    """
    if not governance_enabled():
        return frozenset(declared)
    name = normalize_role(role)
    if not name:
        # 过渡期：网关还没下发 X-User-Role，保持现有"权限集合即事实"的口径。
        return frozenset(declared)
    baseline = role_permissions(name)
    declared = frozenset(declared)
    if declared:
        return baseline & declared
    # 网关只下发了角色、没下发权限头：默认按"没有权限"处理（fail-closed），
    # 避免网关漏发权限头反而变成"授予角色全集"；需要恢复回落行为时显式打开
    # TENANT_ROLE_EMPTY_PERMISSIONS_FALLBACK。
    return baseline if settings.tenant_role_empty_permissions_fallback else frozenset()


def harden_principal(principal: Principal) -> Principal:
    """网关第一跳的落地点：校验角色身份并收敛权限；返回**同一个对象**表示无需改动。"""
    if not governance_enabled() or not principal.role:
        return principal
    name = normalize_role(principal.role)
    if name not in ROLES:
        raise HTTPException(403, f"unknown tenant role: {name or '(empty)'}")
    if not principal.user_id or not principal.tenant_id:
        raise HTTPException(403, f"{name} requires a complete tenant identity (user + tenant)")
    permissions = effective_permissions(name, principal.permissions)
    if permissions == principal.permissions:
        return principal
    return replace(principal, permissions=permissions)


def role_scope(principal: Principal) -> str:
    spec = role_spec(principal.role)
    return spec.scope if spec else ""


def require_tenant_scope(principal: Principal, requested: str = "") -> str:
    """租户范围收口：治理视角允许平台管理员指名租户，其余角色跨租户一律拒绝。

    注意这里只决定"能不能对某个租户做治理动作"，**不**决定内容可见性；
    内容读取永远再走一次 `Principal.can_read`（跨租户内容对任何角色都不可见）。
    """
    if not principal.authenticated:
        raise HTTPException(403, "trusted tenant identity required")
    requested = (requested or "").strip()[:64]
    if not requested or requested == principal.tenant_id:
        return principal.tenant_id
    if normalize_role(principal.role) == PLATFORM_ADMIN or "agent:admin" in principal.permissions:
        # 平台管理员，或过渡期里持有 agent:admin 的运维身份（网关尚未下发角色头）——
        # 与"过渡期不收紧"的既有口径保持一致，不让新端点反而更受限。
        return requested
    raise HTTPException(403, "cross-tenant governance requires platform administrator")


def filter_visible(
    rows: Iterable,
    principal: Principal,
    *,
    level_of: Callable[[object], str],
    tenant_of: Callable[[object], str],
    department_of: Callable[[object], str] | None = None,
    owner_of: Callable[[object], str] | None = None,
) -> tuple[list, int]:
    """检索末条 filter：结果出站前逐条复核，返回 (可见行, 被拒绝条数)。

    未知密级按"不可读"处理而不是猜成 public —— 宁可少给，不可越权。
    """
    visible: list = []
    rejected = 0
    for row in rows:
        try:
            level = str(level_of(row) or "")
        except Exception:  # noqa: BLE001  取不到密级字段视为不可判定
            level = ""
        tenant = (tenant_of(row) or "") if tenant_of else ""
        department = (department_of(row) or "") if department_of else ""
        owner = (owner_of(row) or "") if owner_of else ""
        if level not in DataLevel.__members__:
            rejected += 1
            continue
        if principal.can_read(level, tenant, department, owner):
            visible.append(row)
        else:
            rejected += 1
    return visible, rejected


def access_diagnostics(principal: Principal, *, filtered: int = 0, scope: str = "") -> dict:
    """检索诊断里附带的口径说明：角色、租户范围、被末条 filter 拒掉的条数。"""
    return {
        "role": normalize_role(principal.role) or "legacy",
        "scope": scope or (principal.tenant_id if principal.authenticated else ""),
        "filtered": int(filtered),
        "governanceEnabled": governance_enabled(),
    }


def responsibility_matrix() -> dict:
    """对外导出的职责映射表：端点 `/api/agent/roles`、文档与测试共用同一份事实。"""
    roles = []
    for spec in ROLES.values():
        roles.append({
            "name": spec.name,
            "title": spec.title,
            "scope": spec.scope,
            "boundary": spec.boundary,
            "permissions": sorted(spec.permissions),
            "responsibilities": [
                {"capability": key, "title": CAPABILITY_PERMISSIONS[key][0],
                 "permission": CAPABILITY_PERMISSIONS[key][1]}
                for key in spec.responsibilities
            ],
        })
    return {
        "roles": roles,
        "headers": {"role": ROLE_HEADER, "targetTenant": TARGET_TENANT_HEADER},
        "enforcementPoints": [
            {"stage": "gateway-first-hop", "location": "app/observability.py",
             "action": "未知角色 / 缺租户身份 403；权限按角色基线收敛"},
            {"stage": "route", "location": "app/agent/governance.py::require_route_permission",
             "action": "管理面路径在进业务前按角色权限拦截"},
            {"stage": "retrieval-filter", "location": "app/agent/knowledge.py, app/services/policy.py",
             "action": "结果出站前逐条复核租户 / 密级 / 部门 / 属主并记拒绝条数"},
        ],
        "hardBoundaries": [
            "普通用户不能写 / 发布 / 审计，只能只读检索与自己的记忆",
            "租户管理员不能操作 agent:admin（平台开关、跨租户治理）",
            "任何角色都不能跨租户读内容：跨租户只放行治理元数据",
        ],
        "knownDesignBoundaries": [
            "政策域（public:policy）是全局公共法规库：不参与租户隔离，写入内容对所有租户可见；"
            "租户私有内容必须走素材域 / 知识域（tenant:<tenant>:…）。",
            "角色与密级正交：角色不改变 clearance，高密级仍由网关下发的 X-Data-Clearance 决定。",
        ],
        "legacy": (
            "网关未下发 X-User-Role 时不收紧（role 为空即过渡期口径）；"
            "TENANT_ROLE_GOVERNANCE_ENABLED=false 可整体回退。"
        ),
    }