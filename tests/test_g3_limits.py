"""G3 资源隔离：租户令牌桶 / 并发配额 / 耗时链路容量池。

口径：单租户打满只能影响自己；超限快速失败（429 或降级），不排队拖垮全站。
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import main as app_main
from app.agent.platform_models import GovernanceAudit
from app.agent.runtime import RunCapture, current_run
from app.config import settings
from app.resource_guard import Limiter, Quota, load_quota_config
from app.services import capacity


@pytest.fixture(autouse=True)
def clean_pools():
    capacity.reset()
    yield
    capacity.reset()


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app_db.Base.metadata.create_all(bind=engine)
    for module in (app_db, app_main):
        monkeypatch.setattr(module, "engine", engine)
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(app_main, "load_seed_templates", lambda db: 0)
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    monkeypatch.setattr(settings, "rerank_url", "")
    monkeypatch.setattr(settings, "rerank_local_model", "")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    with factory() as db:
        yield db
    engine.dispose()


# ===== 令牌桶 =====

def test_token_bucket_limits_then_recovers():
    now = [0.0]
    limiter = Limiter(clock=lambda: now[0])
    quota = Quota(rps=1.0, burst=2, concurrency=0)
    assert limiter.acquire("t1", quota, 0).allowed
    assert limiter.acquire("t1", quota, 0).allowed
    blocked = limiter.acquire("t1", quota, 0)
    assert blocked.allowed is False
    assert blocked.reason == "tenant_rate"
    assert blocked.retry_after > 0
    now[0] += 1.0
    assert limiter.acquire("t1", quota, 0).allowed


def test_tenant_concurrency_quota_is_isolated():
    limiter = Limiter(clock=lambda: 0.0)
    quota = Quota(rps=1000.0, burst=1000, concurrency=2)
    assert limiter.acquire("a", quota, 0).allowed
    assert limiter.acquire("a", quota, 0).allowed
    blocked = limiter.acquire("a", quota, 0)
    assert blocked.allowed is False
    assert blocked.reason == "tenant_concurrency"
    # 同一时刻另一个租户不受影响：这是"单租户打满不挤占其他租户"的最小证明
    assert limiter.acquire("b", quota, 0).allowed
    limiter.release("a")
    assert limiter.acquire("a", quota, 0).allowed


def test_global_concurrency_caps_all_tenants():
    limiter = Limiter(clock=lambda: 0.0)
    quota = Quota(rps=1000.0, burst=1000, concurrency=0)
    assert limiter.acquire("a", quota, 1).allowed
    blocked = limiter.acquire("b", quota, 1)
    assert blocked.allowed is False
    assert blocked.reason == "global_concurrency"
    limiter.release("a")
    assert limiter.acquire("b", quota, 1).allowed


def test_quota_overrides_are_tenant_scoped(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_rps", 10.0)
    monkeypatch.setattr(settings, "rate_limit_burst", 10)
    monkeypatch.setattr(settings, "rate_limit_max_concurrency", 4)
    monkeypatch.setattr(
        settings, "rate_limit_tenant_overrides",
        '{"tenant-a": {"rps": 1, "burst": 2, "concurrency": 1}}',
    )
    monkeypatch.setattr(settings, "rate_limit_global_concurrency", 8)
    config = load_quota_config()
    assert config.quota_for("tenant-a") == Quota(rps=1.0, burst=2, concurrency=1)
    assert config.quota_for("other") == Quota(rps=10.0, burst=10, concurrency=4)
    assert config.global_concurrency == 8


# ===== 耗时链路容量池 =====

def test_capacity_pool_fast_fails_when_saturated(monkeypatch):
    monkeypatch.setattr(settings, "rerank_pool_workers", 1)
    monkeypatch.setattr(settings, "rerank_pool_queue", 0)
    release = threading.Event()
    started = threading.Event()

    def slow():
        started.set()
        release.wait(5)
        return "ok"

    worker = threading.Thread(target=lambda: capacity.run("rerank", slow))
    worker.start()
    try:
        assert started.wait(2)
        with pytest.raises(capacity.CapacityError):
            capacity.run("rerank", lambda: "must-not-run")
    finally:
        release.set()
        worker.join(5)
    assert capacity.run("rerank", lambda: "ok") == "ok"


def test_capacity_pool_propagates_agent_context(monkeypatch):
    monkeypatch.setattr(settings, "llm_pool_workers", 2)
    monkeypatch.setattr(settings, "llm_pool_queue", 1)
    capture = RunCapture(intent="g3-test")
    token = current_run.set(capture)
    try:
        seen = capacity.run("llm", lambda: current_run.get() is capture)
    finally:
        current_run.reset(token)
    assert seen is True


def test_capacity_pool_disabled_executes_inline(monkeypatch):
    monkeypatch.setattr(settings, "embedding_pool_workers", 0)
    assert capacity.run("embedding", lambda: "inline") == "inline"


# ===== HTTP 中间件：只拒绝超配额租户 =====

def test_middleware_rejects_only_the_over_quota_tenant(database, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_rps", 100.0)
    monkeypatch.setattr(settings, "rate_limit_burst", 100)
    monkeypatch.setattr(settings, "rate_limit_max_concurrency", 0)
    monkeypatch.setattr(settings, "rate_limit_global_concurrency", 0)
    monkeypatch.setattr(
        settings, "rate_limit_tenant_overrides",
        '{"noisy": {"rps": 0.001, "burst": 2, "concurrency": 0}}',
    )
    headers = {
        "X-Internal-Token": settings.ai_internal_token,
        "X-User-Id": "bench-user", "X-User-Permissions": "policy:read",
    }
    with TestClient(app_main.app) as client:
        noisy = [
            client.get("/api/policy/search", params={"q": "研发补助"},
                       headers={**headers, "X-Tenant-Id": "noisy"})
            for _ in range(3)
        ]
        quiet = client.get("/api/policy/search", params={"q": "研发补助"},
                           headers={**headers, "X-Tenant-Id": "quiet"})

    assert [response.status_code for response in noisy] == [200, 200, 429]
    assert int(noisy[-1].headers["Retry-After"]) >= 1
    assert noisy[-1].json()["detail"]["reason"] == "tenant_rate"
    assert noisy[-1].json()["detail"]["tenant"] == "noisy"
    assert quiet.status_code == 200
    assert "X-RateLimit-Limit" in quiet.headers


def test_middleware_exempts_health_and_honours_disable_switch(database, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_burst", 1)
    monkeypatch.setattr(settings, "rate_limit_rps", 0.001)
    monkeypatch.setattr(settings, "rate_limit_max_concurrency", 0)
    monkeypatch.setattr(settings, "rate_limit_global_concurrency", 0)
    monkeypatch.setattr(settings, "rate_limit_tenant_overrides", "")
    headers = {
        "X-Internal-Token": settings.ai_internal_token,
        "X-User-Id": "bench-user", "X-User-Permissions": "policy:read",
    }
    with TestClient(app_main.app) as client:
        for _ in range(3):
            assert client.get("/api/health").status_code == 200
        assert client.get("/api/policy/search", params={"q": "a"}, headers=headers).status_code == 200
        assert client.get("/api/policy/search", params={"q": "a"}, headers=headers).status_code == 429
        # 关闭开关后立即恢复直通，不需要重启
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        assert client.get("/api/policy/search", params={"q": "a"}, headers=headers).status_code == 200


def test_throttle_audit_persists_only_when_enabled(database, monkeypatch):
    """限流留痕默认关闭（高频拒绝落库会反噬服务），显式打开后必须留痕。"""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_rps", 0.001)
    monkeypatch.setattr(settings, "rate_limit_burst", 1)
    monkeypatch.setattr(settings, "rate_limit_max_concurrency", 0)
    monkeypatch.setattr(settings, "rate_limit_global_concurrency", 0)
    monkeypatch.setattr(settings, "rate_limit_tenant_overrides", "")
    headers = {
        "X-Internal-Token": settings.ai_internal_token,
        "X-User-Id": "bench-user", "X-User-Permissions": "policy:read",
    }
    with TestClient(app_main.app) as client:
        client.get("/api/policy/search", params={"q": "a"}, headers=headers)
        rejected = client.get("/api/policy/search", params={"q": "a"}, headers=headers)
    assert rejected.status_code == 429
    database.rollback()
    assert database.query(GovernanceAudit).filter_by(action="ratelimit.reject").count() == 0

    monkeypatch.setattr(settings, "rate_limit_audit_enabled", True)
    with TestClient(app_main.app) as client:
        client.get("/api/policy/search", params={"q": "a"}, headers=headers)
        rejected = client.get("/api/policy/search", params={"q": "a"}, headers=headers)
    assert rejected.status_code == 429
    database.rollback()
    rows = database.query(GovernanceAudit).filter_by(action="ratelimit.reject").all()
    assert rows and rows[0].outcome == "denied"
    assert rows[0].details["reason"] in {"tenant_rate", "tenant_concurrency", "global_concurrency"}


def test_unauthenticated_requests_are_not_masked_as_throttling(database, monkeypatch):
    """未认证请求不消耗租户配额：403 不得被 429 掩盖（鉴权失败与限流是两件事）。"""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_burst", 1)
    monkeypatch.setattr(settings, "rate_limit_rps", 0.001)
    monkeypatch.setattr(settings, "rate_limit_tenant_overrides", "")
    with TestClient(app_main.app) as client:
        statuses = [client.get("/api/agent/registry").status_code for _ in range(4)]
    assert statuses == [403, 403, 403, 403]


def test_llm_pool_saturation_degrades_draft_instead_of_failing(monkeypatch):
    """LLM 池满属于可归因的过载：公告链路应降级为规则化草稿并写进 riskFlags，而不是 5xx。"""
    from app.graphs import drafting
    from app.services.llm import LLMCapacityError, LLMClient

    monkeypatch.setattr(settings, "llm_api_key", "")

    def saturated(*args, **kwargs):
        raise LLMCapacityError("llm 容量已满（queue_full），已快速失败")

    monkeypatch.setattr(drafting, "generate_content", saturated)
    state = {
        "request": {"title": "项目启动会新闻稿", "style": "正式",
                    "eventDesc": "测试公司于2026年10月11日召开项目启动会。"},
        "template": {"id": "tpl", "name": "新闻稿", "tone_guidelines": ""},
        "elements": [{"name": "发布日期", "value": "2026年10月11日"}],
        "materials": "",
    }
    generated = drafting.generate_node(state, LLMClient())
    draft = generated["drafts"][0]
    assert draft["degraded"] is True
    assert draft["degradeReason"] == "llm-pool-saturated"
    assert draft["content"] and "error" not in draft
    # 降级文案必须说清真实原因，不能让人去改一个与故障无关的配置
    assert "容量不足" in draft["content"]
    assert "配置 LLM_API_KEY" not in draft["content"]

    flags = drafting.suggest_node({**state, **generated}, LLMClient())["risk_flags"]
    assert any("降级" in flag for flag in flags)