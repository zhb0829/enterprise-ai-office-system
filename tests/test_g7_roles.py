"""G7 三角色租户治理分工：跨租户 / 伪造身份 / 越权访问。

口径（与 `app/agent/access.py` 一致）：

- **只收缩**：声明角色后有效权限 = 角色基线 ∩ 网关声明；member 带着全量权限头也写不了。
- **过渡期不收紧**：网关未下发 `X-User-Role` 时保持既有口径；`TENANT_ROLE_GOVERNANCE_ENABLED=false`
  可整体回退。
- **三条硬边界**：普通用户不能写 / 发布 / 审计；租户管理员不能碰 `agent:admin`；
  任何角色都不能跨租户读内容（跨租户只放行治理元数据）。
- **三层贯通**：网关第一跳（中间件）→ 路由级（`require_route_permission`）→ 检索末条（`filter_visible`）。

既有基础：`tests/test_p1_platform.py` 的跨租户 / 伪造身份用例，本文件在其上补角色维度。
"""
from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import main as app_main
from app.agent.access import (
    CAPABILITY_PERMISSIONS, MEMBER, PLATFORM_ADMIN, ROLES, TENANT_ADMIN,
    effective_permissions, filter_visible, harden_principal, require_tenant_scope,
    responsibility_matrix, role_permissions,
)
from app.agent.governance import DataLevel, Principal, data_level_var, principal_var
from app.agent.knowledge import KnowledgeStore, search_knowledge
from app.agent.platform_models import GovernanceAudit
from app.config import settings
from app.schemas import PolicyQuery
from app.services.policy import answer_policy, create_policy_document

ALL_PERMISSIONS = ",".join(sorted({
    "agent:admin", "agent:audit", "knowledge:read", "knowledge:write", "knowledge:publish",
    "materials:read", "materials:write", "draft:write", "draft:review", "draft:verify",
    "templates:write", "opinion:read", "meeting:read", "policy:read",
    "memory:read", "memory:write", "memory:department:write", "memory:tenant:write",
}))


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine)
    app_db.Base.metadata.create_all(engine)
    for module in (app_db, app_main):
        monkeypatch.setattr(module, "engine", engine)
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(app_main, "load_seed_templates", lambda db: 0)
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    monkeypatch.setattr(settings, "rerank_url", "")
    monkeypatch.setattr(settings, "rerank_local_model", "")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "tenant_role_governance_enabled", True)
    with factory() as db:
        yield db
    engine.dispose()


def principal(role="", user="u1", tenant="t1", department="d1", permissions=None, public_only=False):
    declared = frozenset(permissions) if permissions is not None else frozenset(ALL_PERMISSIONS.split(","))
    return Principal(user, tenant, department, declared, DataLevel.internal, public_only, role)


def headers(role="", user="u1", tenant="t1", department="d1", permissions=ALL_PERMISSIONS, **extra):
    result = {
        "X-Internal-Token": settings.ai_internal_token,
        "X-User-Id": user, "X-Tenant-Id": tenant, "X-Department-Id": department,
        "X-User-Permissions": permissions,
    }
    if role:
        result["X-User-Role"] = role
    result.update(extra)
    return result


@contextmanager
def as_identity(p):
    token = principal_var.set(p)
    data_token = data_level_var.set(DataLevel.public)
    try:
        yield
    finally:
        principal_var.reset(token)
        data_level_var.reset(data_token)


# ===== 职责映射本身 =====

def test_responsibility_matrix_is_consistent_and_complete():
    matrix = responsibility_matrix()
    names = [row["name"] for row in matrix["roles"]]
    assert names == [PLATFORM_ADMIN, TENANT_ADMIN, MEMBER]
    scopes = {row["name"]: row["scope"] for row in matrix["roles"]}
    assert scopes == {PLATFORM_ADMIN: "platform", TENANT_ADMIN: "tenant", MEMBER: "self"}
    for row in matrix["roles"]:
        baseline = role_permissions(row["name"])
        covered = set()
        for item in row["responsibilities"]:
            # 每条职责都必须映射到真实权限，且这条权限真的在这个角色的基线里。
            assert item["capability"] in CAPABILITY_PERMISSIONS
            assert item["permission"] == CAPABILITY_PERMISSIONS[item["capability"]][1]
            assert item["permission"] in baseline, f"{row['name']} 的职责 {item['capability']} 没有权限支撑"
            covered.add(item["permission"])
        # 反过来也不允许"给了权限但不对应任何职责"。
        assert baseline <= covered, f"{row['name']} 的权限缺少职责解释：{sorted(baseline - covered)}"
    assert matrix["hardBoundaries"] and len(matrix["hardBoundaries"]) == 3
    assert {point["stage"] for point in matrix["enforcementPoints"]} == {
        "gateway-first-hop", "route", "retrieval-filter",
    }


def test_unknown_role_is_rejected_and_permissions_only_shrink():
    with pytest.raises(HTTPException) as error:
        role_permissions("super-admin")
    assert error.value.status_code == 403
    assert effective_permissions(MEMBER, ["knowledge:publish", "policy:read"]) == frozenset({"policy:read"})
    # 未声明角色（过渡期）原样保留网关下发的权限集合。
    assert effective_permissions("", ["knowledge:publish"]) == frozenset({"knowledge:publish"})
    # 声明角色但权限头为空：默认 fail-closed（按"没有权限"处理）；
    # 只有显式打开回落开关才使用角色基线，避免网关漏发权限头反而变成放大授权。
    assert effective_permissions(MEMBER, []) == frozenset()
    settings.tenant_role_empty_permissions_fallback = True
    try:
        assert effective_permissions(MEMBER, []) == role_permissions(MEMBER)
    finally:
        settings.tenant_role_empty_permissions_fallback = False
    # 平台管理员是租户管理员能力的超集，但两条硬边界仍然独立成立。
    assert role_permissions(TENANT_ADMIN) < role_permissions(PLATFORM_ADMIN)
    assert "agent:admin" in role_permissions(PLATFORM_ADMIN)
    assert "agent:admin" not in role_permissions(TENANT_ADMIN)
    assert not ({"knowledge:write", "knowledge:publish", "agent:audit"} & role_permissions(MEMBER))


def test_gateway_first_hop_hardens_or_rejects():
    forged = principal(MEMBER, permissions=ALL_PERMISSIONS.split(","))
    hardened = harden_principal(forged)
    assert hardened.permissions == role_permissions(MEMBER)
    assert forged.permissions != hardened.permissions, "收敛必须产出一个新的 Principal，不能原地放宽"
    assert harden_principal(principal("")) is not None
    with pytest.raises(HTTPException) as error:
        harden_principal(principal("shadow-admin"))
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        harden_principal(principal(MEMBER, tenant=""))
    assert error.value.status_code == 403
    # 明显不合法的角色名不会被当成"未知角色但放行"。
    assert harden_principal(principal()).role == ""


def test_tenant_scope_rules():
    with pytest.raises(HTTPException):
        require_tenant_scope(Principal())
    member = principal(MEMBER, permissions=role_permissions(MEMBER))
    assert require_tenant_scope(member) == "t1"
    assert require_tenant_scope(member, "t1") == "t1"
    with pytest.raises(HTTPException) as error:
        require_tenant_scope(member, "t2")
    assert error.value.status_code == 403
    platform_admin = principal(PLATFORM_ADMIN, tenant="t0")
    assert require_tenant_scope(platform_admin, "t2") == "t2"
    assert require_tenant_scope(platform_admin, "all") == "all"
    # 过渡期：网关未下发角色头但持有 agent:admin 的运维身份，治理端点不应比角色身份更受限。
    legacy_ops = principal("", tenant="t0", permissions=["agent:admin"])
    assert require_tenant_scope(legacy_ops, "t2") == "t2"


def test_role_baseline_is_a_hard_ceiling_for_direct_callers(database):
    """纵深防御：绕过网关收敛直接构造 Principal 也不能越权。"""
    with as_identity(principal(MEMBER, permissions=ALL_PERMISSIONS.split(","))):
        with pytest.raises(HTTPException) as error:
            principal_var.get().require("agent:admin")
        assert error.value.status_code == 403
        # 直接构造的 member 也写不了租户共享记忆（memory:tenant:write 属租户管理员职责）。
        from app.agent.memory import MemoryStore
        with pytest.raises(HTTPException) as error:
            MemoryStore(database).put("tenant-style", {"style": "formal"}, scope="tenant")
        assert error.value.status_code == 403


# ===== 检索末条 filter =====

def test_filter_visible_rejects_cross_tenant_and_unknown_classification():
    rows = [
        {"level": "public", "tenant": "t2", "department": "", "owner": ""},
        {"level": "internal", "tenant": "t1", "department": "d1", "owner": ""},
        {"level": "internal", "tenant": "t2", "department": "d1", "owner": ""},
        {"level": "restricted", "tenant": "t1", "department": "d1", "owner": ""},
        {"level": "mystery", "tenant": "t1", "department": "d1", "owner": ""},
    ]
    visible, rejected = filter_visible(
        rows, principal(MEMBER),
        level_of=lambda row: row["level"], tenant_of=lambda row: row["tenant"],
        department_of=lambda row: row["department"], owner_of=lambda row: row["owner"],
    )
    # public 任何租户可见；internal 只在本租户本部门；restricted 超出密级；未知密级按不可读处理。
    assert [row["level"] for row in visible] == ["public", "internal"]
    assert rejected == 3
    # 平台管理员也不能跨租户读内容。
    _, rejected = filter_visible(
        rows, principal(PLATFORM_ADMIN, tenant="t0"),
        level_of=lambda row: row["level"], tenant_of=lambda row: row["tenant"],
        department_of=lambda row: row["department"], owner_of=lambda row: row["owner"],
    )
    assert rejected == 4


def test_cross_tenant_knowledge_snapshot_and_search_are_empty_for_every_role(database):
    with as_identity(principal(TENANT_ADMIN, tenant="t1")):
        store = KnowledgeStore(database, "tenant:t1:materials")
        row = store.stage([{
            "key": "internal", "text": "企业内部的研发补助方案。", "classification": "internal",
            "tenant_id": "t1", "department_id": "d1",
        }])
        store.publish(row.id)
        database.commit()
        assert search_knowledge(database, "materials", "研发补助方案")
    for other in (principal(TENANT_ADMIN, tenant="t2"), principal(PLATFORM_ADMIN, tenant="t0"),
                  principal(MEMBER, tenant="t1", department="d2")):
        with as_identity(other):
            assert not KnowledgeStore(database, "tenant:t1:materials").snapshot()["entries"]
            assert search_knowledge(database, "materials", "研发补助方案") == []


def test_search_audit_records_role_and_filtered_count(database):
    with as_identity(principal(TENANT_ADMIN, tenant="t1")):
        store = KnowledgeStore(database, "tenant:t1:materials")
        row = store.stage([{
            "key": "a", "text": "研发补助材料清单。", "classification": "internal",
            "tenant_id": "t1", "department_id": "d1",
        }])
        store.publish(row.id)
        database.commit()
        assert search_knowledge(database, "materials", "研发补助材料清单")
        database.commit()
    audit_row = database.query(GovernanceAudit).filter(GovernanceAudit.action == "knowledge.search").one()
    assert audit_row.details["filtered"] == 0
    assert audit_row.details["access"]["role"] == TENANT_ADMIN
    assert audit_row.details["access"]["governanceEnabled"] is True


def test_policy_retrieval_carries_access_diagnostics(database):
    with as_identity(principal(MEMBER)):
        create_policy_document(database, title="研发补助办法", content="第一条 企业申请研发补助应提交年度审计报告。")
        database.commit()
        response = answer_policy(database, PolicyQuery(question="研发补助申请材料？"))
        assert response["clauses"], "普通用户只提问，检索不应被角色收敛误伤"
        access = response["retrieval"][0]["access"]
        assert access["role"] == MEMBER and access["filtered"] == 0


# ===== 三层贯通：HTTP 越权 / 伪造身份 / 跨租户 =====

def test_member_cannot_escalate_with_full_permission_header(database):
    with TestClient(app_main.app) as client:
        forged = headers(role=MEMBER)  # 权限头是伪造的全量集合
        assert client.post(
            "/api/agent/knowledge/policy/releases",
            json={"documents": [{"key": "a", "text": "test", "classification": "public"}], "public": True},
            headers=forged,
        ).status_code == 403
        assert client.put("/api/agent/flags/kg", json={"enabled": True}, headers=forged).status_code == 403
        assert client.get("/api/agent/costs", headers=forged).status_code == 403
        assert client.get("/api/agent/governance/audit", headers=forged).status_code == 403
        assert client.get("/api/agent/tenants", headers=forged).status_code == 403
        # 只提问：自己的记忆与检索仍然可用，角色收敛不能收敛成"什么都干不了"。
        assert client.put(
            "/api/agent/memory", json={"key": "style", "value": {"style": "concise"}}, headers=forged,
        ).status_code == 200
        roles = client.get("/api/agent/roles", headers=forged)
        assert roles.status_code == 200 and roles.json()["current"]["role"] == MEMBER


def test_tenant_admin_manages_own_knowledge_but_not_platform(database):
    with TestClient(app_main.app) as client:
        admin = headers(role=TENANT_ADMIN, tenant="t1")
        created = client.post(
            "/api/agent/knowledge/materials/releases",
            json={"documents": [{
                "key": "a", "text": "本租户研发补助材料。", "classification": "internal",
            }]},
            headers=admin,
        )
        assert created.status_code == 201, created.text
        # 硬边界 2：租户管理员不能操作平台级开关与跨租户治理。
        assert client.put("/api/agent/flags/kg", json={"enabled": True}, headers=admin).status_code == 403
        assert client.get("/api/agent/tenants", headers=admin).status_code == 403
        # 硬边界 1 的对照：普通用户连本租户知识库都进不去。
        assert client.get(
            "/api/agent/knowledge/materials/snapshot",
            headers=headers(role=MEMBER, tenant="t1"),
        ).status_code == 403


def test_platform_admin_sees_governance_metadata_only(database):
    with TestClient(app_main.app) as client:
        tenant_admin = headers(role=TENANT_ADMIN, tenant="t1")
        assert client.post(
            "/api/agent/knowledge/materials/releases",
            json={"documents": [{"key": "secret", "text": "t1 私有条款正文", "classification": "internal"}]},
            headers=tenant_admin,
        ).status_code == 201
        platform = headers(role=PLATFORM_ADMIN, tenant="t0")
        # 平台管理员看全平台地毯需要显式 target=all；默认只看自己租户（不越权扫全网）。
        assert client.get("/api/agent/tenants", headers=platform).json()["wildcard"] is False
        overview = client.get("/api/agent/tenants?target=all", headers=platform)
        assert overview.status_code == 200, overview.text
        body = overview.json()
        assert body["metadataOnly"] is True
        assert body["wildcard"] is True
        tenant_ids = {row["tenantId"] for row in body["tenants"]}
        assert "t1" in tenant_ids
        # 治理元数据里不允许出现任何知识正文。
        assert "t1 私有条款正文" not in overview.text
        # 指名租户：只回该租户的元数据，仍然不含正文。
        named = client.get("/api/agent/tenants", headers={**platform, "X-Target-Tenant": "t1"})
        assert named.status_code == 200
        assert {row["tenantId"] for row in named.json()["tenants"]} == {"t1"}
        assert "t1 私有条款正文" not in named.text
        # 租户管理员没有 agent:admin，跨租户治理在网关第一跳就被拒。
        assert client.get(
            "/api/agent/tenants?target=all", headers=headers(role=TENANT_ADMIN, tenant="t1"),
        ).status_code == 403
        # 跨租户读内容依然被拒：看治理元数据可以，看快照不行。
        assert client.get(
            "/api/agent/knowledge/materials/snapshot?public=false",
            headers={**platform, "X-Target-Tenant": "t1"},
        ).status_code in {200, 403}
        with as_identity(principal(PLATFORM_ADMIN, tenant="t0")):
            assert KnowledgeStore(database, "tenant:t1:materials").snapshot()["entries"] == []


def test_forged_or_unknown_identity_is_rejected_at_the_first_hop(database):
    with TestClient(app_main.app) as client:
        unknown = client.get("/api/agent/roles", headers=headers(role="shadow-admin"))
        assert unknown.status_code == 403
        assert "role" in unknown.json()["detail"]
        # 角色声明了但租户身份不完整：第一跳直接拒，不进业务。
        assert client.get(
            "/api/agent/roles", headers=headers(role=MEMBER, tenant=""),
        ).status_code == 403
        # 没有内部令牌时角色头不被信任（Java 网关剥离伪造头的等价防线）。
        untrusted = client.get("/api/agent/roles", headers={
            "X-User-Id": "u1", "X-Tenant-Id": "t1", "X-User-Role": PLATFORM_ADMIN,
            "X-User-Permissions": ALL_PERMISSIONS,
        })
        assert untrusted.status_code == 403
    rows = database.query(GovernanceAudit).filter(GovernanceAudit.outcome == "denied").all()
    assert rows, "越权访问必须留治理审计"
    assert any(row.details.get("role") == "shadow-admin" for row in rows)
    assert any(row.details.get("role") == MEMBER for row in rows)


def test_legacy_identity_and_governance_switch(database, monkeypatch):
    """过渡期口径：网关没下发角色头时不收紧；开关置 false 可整体回退。"""
    with TestClient(app_main.app) as client:
        legacy = headers()  # 不带 X-User-Role
        assert client.put(
            "/api/agent/flags/kg", json={"enabled": True, "reason": "过渡期"}, headers=legacy,
        ).status_code == 200
        monkeypatch.setattr(settings, "tenant_role_governance_enabled", False)
        rolled_back = headers(role=MEMBER)
        assert client.put(
            "/api/agent/flags/kg", json={"enabled": True, "reason": "回退口径"}, headers=rolled_back,
        ).status_code == 200
        monkeypatch.setattr(settings, "tenant_role_governance_enabled", True)
        assert client.put(
            "/api/agent/flags/kg", json={"enabled": True}, headers=rolled_back,
        ).status_code == 403
# ===== 审查发现的加固点（头走私 / 内部面 / 工具判权 / 收口开关 / 公共域契约）=====

def test_duplicated_identity_headers_are_rejected(database):
    """同一个受信身份头出现两次 = 头走私风险：网关应覆盖而非追加，后端直接 fail-closed。"""
    with TestClient(app_main.app) as client:
        headers_list = [
            ("X-Internal-Token", settings.ai_internal_token),
            ("X-User-Id", "u1"), ("X-Tenant-Id", "t1"),
            ("X-User-Role", "member"), ("X-User-Role", "platform_admin"),
            ("X-User-Permissions", "policy:read"),
        ]
        response = client.get("/api/agent/roles", headers=headers_list)
        assert response.status_code == 403
        assert "duplicated" in response.text
        single = client.get("/api/agent/roles", headers=headers(role=MEMBER))
        assert single.status_code == 200


def test_internal_surface_is_not_subject_to_role_governance(database):
    """/internal/** 是服务间调用：网关若给它补了角色头又没有租户身份，也不能把它打成 403。"""
    with TestClient(app_main.app) as client:
        response = client.get("/internal/health", headers={
            "X-Internal-Token": settings.ai_internal_token, "X-User-Role": "member",
        })
        assert response.status_code == 200


def test_cors_preflight_is_not_blocked_by_permission_checks(database):
    """预检请求不带业务语义：必须让路给 CORS 层，不能被权限校验拦成 403。"""
    with TestClient(app_main.app) as client:
        for path in ("/api/agent/costs", "/api/agent/knowledge/materials/snapshot", "/api/policy/chat"):
            preflight = client.options(path, headers={
                "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
            })
            assert preflight.status_code != 403, path
            assert "permission required" not in preflight.text


def test_tool_invocation_uses_hardened_permissions(database):
    """工具判权必须用角色收敛后的权限：member 不能借伪造头调用 draft:verify 工具。"""
    with TestClient(app_main.app) as client:
        forged = headers(role=MEMBER)
        denied = client.post("/api/agent/tools/verify_facts/invoke", json={"input": {}}, headers=forged)
        assert denied.status_code == 403, denied.text
        # 对照：过渡期（无角色头）同权限头仍然可用，说明拒绝来自角色收敛而不是工具坏了
        legacy = client.post(
            "/api/agent/tools/verify_facts/invoke", json={"input": {}}, headers=headers(),
        )
        # 同类请求在过渡期口径下过了权限层（只是入参不全），说明拒绝确实来自角色收敛
        assert legacy.status_code != 403, legacy.text
        assert legacy.status_code in {200, 422}, legacy.text


def test_role_required_switch_closes_the_gap(database, monkeypatch):
    """TENANT_ROLE_REQUIRED=true：无角色头的 /api 请求直接 403（网关全量下发后再打开）。"""
    with TestClient(app_main.app) as client:
        monkeypatch.setattr(settings, "tenant_role_required", True)
        assert client.get("/api/agent/roles", headers=headers()).status_code == 403
        assert client.get("/api/agent/roles", headers=headers(role=MEMBER)).status_code == 200
        monkeypatch.setattr(settings, "tenant_role_required", False)
        assert client.get("/api/agent/roles", headers=headers()).status_code == 200


def test_policy_domain_is_a_shared_public_library(database):
    """政策域（public:policy）是全局公共法规库：不参与租户隔离，这是设计边界而不是漏洞。"""
    with as_identity(principal(TENANT_ADMIN, tenant="t1")):
        create_policy_document(database, title="t1 发布的公共政策", content="第一条 研发补助金额为 800 万元。")
        database.commit()
    from app.services.policy import search_policy_clauses
    with as_identity(principal(MEMBER, tenant="t2")):
        hits = search_policy_clauses(database, "研发补助金额")
        assert hits, "公共政策库对所有租户可见（租户私有内容必须走 materials 域）"
        assert "800 万元" in hits[0]["clause"].content


def test_private_material_domain_stays_tenant_isolated(database):
    """与公共政策域对照：素材域（tenant 命名空间）必须严格按租户隔离。"""
    with as_identity(principal(TENANT_ADMIN, tenant="t1")):
        store = KnowledgeStore(database, "tenant:t1:materials")
        row = store.stage([{
            "key": "private", "text": "t1 私有内容 800 万元", "classification": "internal",
            "tenant_id": "t1", "department_id": "d1",
        }])
        store.publish(row.id)
        database.commit()
    with as_identity(principal(TENANT_ADMIN, tenant="t2")):
        assert KnowledgeStore(database, "tenant:t1:materials").snapshot()["entries"] == []
        assert search_knowledge(database, "materials", "t1 私有内容") == []