"""G6 成本核算：价格表口径、未知成本记 null、按租户/功能/模型聚合与查询端点。

红线：模型未收录、或供应商没返回 usage 时，成本必须是 null——不用 0 顶替、不估算；
部分已知时 `cost` 只含已定价部分，同时必须能看出缺口（costComplete / unpricedModels）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import main as app_main
from app.agent.models import AgentRun
from app.agent.runtime import RunCapture, current_run
from app.config import settings
from app.services import cost
from app.services.llm import LLMClient
from app.schemas import PolicyQuery
from app.services.policy import answer_policy, create_policy_document

PRICE_TABLE = (
    '{"priced-chat": {"input": 2, "output": 8}, "priced-light": {"input": 0.5, "output": 1},'
    ' "deepseek-chat": {"input": 2, "output": 8}}'
)


@pytest.fixture(autouse=True)
def isolated_price_table():
    cost.reset()
    yield
    cost.reset()


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
    monkeypatch.setattr(settings, "llm_price_table", "")
    with factory() as db:
        yield db
    engine.dispose()


def _usage_with(*calls) -> dict:
    """把若干次调用累加成一个 usage（走真实 accumulate，避免手写结构漂移）。"""
    capture = RunCapture(intent="policy_qa")
    token = current_run.set(capture)
    try:
        for call in calls:
            cost.record_usage(**call)
    finally:
        current_run.reset(token)
    return capture.usage


def _run(tenant: str, usage: dict, *, run_id: str, purpose: str = "policy_qa") -> AgentRun:
    from datetime import datetime, timezone

    return AgentRun(
        run_id=run_id, trace_id="trace-" + run_id, user_id="u", tenant_id=tenant,
        intent=purpose, status="completed", usage=usage, routing={},
        started_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )


def _headers(permissions: str, tenant: str = "default") -> dict:
    return {
        "X-Internal-Token": settings.ai_internal_token,
        "X-User-Id": "ops-user", "X-Tenant-Id": tenant,
        "X-User-Permissions": permissions,
    }


# ===== 价格表解析 =====

def test_price_table_parses_valid_entries(monkeypatch):
    monkeypatch.setattr(settings, "llm_price_table", PRICE_TABLE)
    table = cost.reload_price_table()
    assert table.configured is True
    assert table.price_for("PRICED-CHAT").input_per_million == 2
    assert table.price_for("priced-chat").cost(10, 8) == pytest.approx(0.000084)
    assert table.rejected == [] and not table.error


def test_price_table_rejects_unsafe_entries_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(settings, "llm_price_table", (
        '{"no-output": {"input": 1}, "negative": {"input": -1, "output": 1},'
        ' "usd": {"input": 1, "output": 1, "currency": "USD"},'
        ' "wrong-unit": {"input": 1, "output": 1, "unit": "per_1k_tokens"},'
        ' "not-object": 3, "": {"input": 1, "output": 1},'
        ' "ok": {"input": 1, "output": 2}}'
    ))
    table = cost.reload_price_table()
    assert table.price_for("ok").cost(1_000_000, 1_000_000) == pytest.approx(3)
    reasons = {item["reason"] for item in table.rejected}
    assert "missing-output-price" in reasons, "缺 output 不等于输出免费，必须拒绝"
    assert "invalid-input-price" in reasons
    assert "currency-not-supported:USD" in reasons
    assert "unit-not-supported:per_1k_tokens" in reasons
    assert "entry-not-object" in reasons
    assert "empty-model-name" in reasons
    for model in ("no-output", "negative", "usd", "wrong-unit", "not-object"):
        assert table.price_for(model) is None


def test_price_table_handles_broken_json(monkeypatch):
    monkeypatch.setattr(settings, "llm_price_table", "{not json")
    table = cost.reload_price_table()
    assert table.configured is False
    assert table.rejected == []
    assert "不是合法 JSON" in table.error


# ===== 未知成本一律 null =====

def test_unpriced_model_records_null_cost():
    usage = _usage_with({"model": "unknown-chat", "purpose": "policy.answer",
                         "input_tokens": 10, "output_tokens": 8})
    bucket = usage["by_model"]["unknown-chat"]
    assert usage["cost"] is None, "没有任何已定价模型时不允许编造总额"
    assert usage["cost_complete"] is False
    assert usage["unpriced_models"] == ["unknown-chat"]
    assert bucket["cost"] is None and bucket["cost_complete"] is False
    assert bucket["unpriced_reasons"] == [cost.REASON_MODEL_NOT_PRICED]
    assert bucket["input_tokens"] == 10 and bucket["output_tokens"] == 8


def test_missing_usage_records_calls_but_null_tokens_and_cost():
    usage = _usage_with({"model": "rerank-model", "purpose": "rerank.policy", "tokens_available": False})
    bucket = usage["by_model"]["rerank-model"]
    assert bucket["calls"] == 1
    assert bucket["input_tokens"] is None and bucket["output_tokens"] is None
    assert bucket["cost"] is None
    assert bucket["unpriced_reasons"] == [cost.REASON_TOKEN_USAGE_MISSING]
    assert usage["usage_complete"] is False


def test_one_sided_tokens_are_not_priced(monkeypatch):
    """usage 存在但缺一侧 token（或只回 total_tokens）：按缺失侧 = 0 计价会静默低报。"""
    monkeypatch.setattr(settings, "llm_price_table", PRICE_TABLE)
    cost.reset()
    usage = _usage_with({"model": "priced-chat", "purpose": "policy.answer",
                         "input_tokens": None, "output_tokens": 8})
    bucket = usage["by_model"]["priced-chat"]
    assert bucket["cost"] is None and bucket["cost_complete"] is False
    assert bucket["unpriced_reasons"] == [cost.REASON_TOKEN_USAGE_MISSING]
    assert bucket["tokens_complete"] is False and bucket["input_tokens"] is None
    assert usage["cost"] is None and usage["tokens_complete"] is False


def test_unknown_tokens_stay_unknown_after_later_known_calls(monkeypatch):
    """token 未知不可逆：后续已知调用不得把未知总量"复原"成看起来完整的合计。"""
    monkeypatch.setattr(settings, "llm_price_table", PRICE_TABLE)
    cost.reset()
    usage = _usage_with(
        {"model": "priced-chat", "purpose": "policy.answer", "tokens_available": False},
        {"model": "priced-chat", "purpose": "policy.answer", "input_tokens": 10, "output_tokens": 8},
    )
    bucket = usage["by_model"]["priced-chat"]
    assert bucket["calls"] == 2
    assert bucket["input_tokens"] is None and bucket["output_tokens"] is None
    assert bucket["tokens_complete"] is False
    assert bucket["cost"] == pytest.approx(0.000084), "已知的那一次仍然要计价"
    assert usage["input_tokens"] is None and usage["tokens_complete"] is False


def test_priced_model_computes_cost_and_completeness(monkeypatch):
    monkeypatch.setattr(settings, "llm_price_table", PRICE_TABLE)
    cost.reset()
    usage = _usage_with(
        {"model": "priced-chat", "purpose": "policy.answer", "input_tokens": 10, "output_tokens": 8},
        {"model": "priced-chat", "purpose": "draft.generate", "input_tokens": 90, "output_tokens": 92},
    )
    bucket = usage["by_model"]["priced-chat"]
    assert bucket["calls"] == 2 and bucket["input_tokens"] == 100 and bucket["output_tokens"] == 100
    assert bucket["cost"] == pytest.approx(100 / 1e6 * 2 + 100 / 1e6 * 8)
    assert bucket["cost_complete"] is True
    assert usage["cost"] == pytest.approx(bucket["cost"])
    assert usage["cost_complete"] is True and usage["unpriced_models"] == []
    assert usage["tokens_complete"] is True
    assert usage["currency"] == "CNY" and usage["price_unit"] == cost.UNIT
    assert set(bucket["purposes"]) == {"policy.answer", "draft.generate"}


def test_partial_pricing_exposes_the_gap(monkeypatch):
    monkeypatch.setattr(settings, "llm_price_table", PRICE_TABLE)
    cost.reset()
    usage = _usage_with(
        {"model": "priced-chat", "purpose": "policy.answer", "input_tokens": 10, "output_tokens": 8},
        {"model": "unpriced-chat", "purpose": "policy.answer", "input_tokens": 10, "output_tokens": 8},
    )
    assert usage["cost"] == pytest.approx(0.000084), "cost 只累加已定价部分"
    assert usage["cost_complete"] is False
    assert usage["unpriced_models"] == ["unpriced-chat"]


# ===== 聚合 =====

def test_aggregate_groups_by_model_purpose_tenant(monkeypatch):
    monkeypatch.setattr(settings, "llm_price_table", PRICE_TABLE)
    cost.reset()
    usage_a = _usage_with({"model": "priced-chat", "purpose": "policy.answer",
                           "input_tokens": 10, "output_tokens": 8})
    usage_b = _usage_with({"model": "priced-light", "purpose": "draft.generate",
                           "input_tokens": 1000, "output_tokens": 1000})
    records = [
        {"runId": "r1", "tenantId": "t1", "intent": "policy_qa", "usage": usage_a},
        {"runId": "r2", "tenantId": "t2", "intent": "drafting", "usage": usage_b},
    ]
    report = cost.aggregate(records, group_by=("model", "purpose", "tenant"))
    assert report["currency"] == "CNY" and report["costKnownOnly"] is True
    assert report["costComplete"] is True
    assert report["total"]["runs"] == 2 and report["total"]["calls"] == 2
    assert report["total"]["cost"] == pytest.approx(0.000084 + 1000 / 1e6 * 0.5 + 1000 / 1e6 * 1)
    groups = {(group["model"], group["purpose"], group["tenant"]) for group in report["groups"]}
    assert ("priced-chat", "policy.answer", "t1") in groups
    assert ("priced-light", "draft.generate", "t2") in groups

    by_tenant = cost.aggregate(records, group_by=("tenant",))
    assert {group["tenant"] for group in by_tenant["groups"]} == {"t1", "t2"}
    assert by_tenant["groups"][0]["cost"] is not None

    by_model = cost.aggregate(records, group_by=("model",))
    assert {group["model"] for group in by_model["groups"]} == {"priced-chat", "priced-light"}

    # 业务功能（intent）与模型用途（purpose）是两层口径，必须分别可查
    by_intent = cost.aggregate(records, group_by=("intent",))
    assert {group["intent"] for group in by_intent["groups"]} == {"policy_qa", "drafting"}
    by_purpose = cost.aggregate(records, group_by=("purpose",))
    assert {group["purpose"] for group in by_purpose["groups"]} == {"policy.answer", "draft.generate"}


def test_aggregate_marks_legacy_runs_as_unattributed(monkeypatch):
    monkeypatch.setattr(settings, "llm_price_table", PRICE_TABLE)
    cost.reset()
    legacy = {"input_tokens": 120, "output_tokens": 80, "cost": None, "usage_complete": True}
    report = cost.aggregate(
        [{"runId": "old", "tenantId": "t1", "intent": "policy_qa", "usage": legacy}],
        group_by=("model",),
    )
    assert report["unattributedRuns"] == 1
    group = report["groups"][0]
    assert group["model"] == cost.UNATTRIBUTED
    assert group["cost"] is None and group["costComplete"] is False
    assert group["unpricedReasons"] == [cost.REASON_USAGE_NOT_ATTRIBUTED]
    assert report["total"]["cost"] is None and report["costComplete"] is False


def test_aggregate_ignores_unknown_group_dimensions():
    report = cost.aggregate([], group_by=("nonsense",))
    assert report["groupBy"] == ["model"]


def test_aggregate_exposes_token_completeness(monkeypatch):
    monkeypatch.setattr(settings, "llm_price_table", PRICE_TABLE)
    cost.reset()
    usage = _usage_with({"model": "priced-chat", "purpose": "policy.answer",
                         "input_tokens": None, "output_tokens": 8})
    report = cost.aggregate(
        [{"runId": "r1", "tenantId": "t1", "intent": "policy_qa", "usage": usage}],
        group_by=("model",),
    )
    assert report["tokensComplete"] is False
    assert report["total"]["tokensComplete"] is False
    assert report["groups"][0]["tokensComplete"] is False
    assert report["total"]["cost"] is None, "缺 token 时不得给出金额"


def test_aggregate_skips_runs_without_any_model_usage():
    """离线/规则化链路没有模型用量：不算成本缺口，否则 costComplete 永远为 false。"""
    report = cost.aggregate([{
        "runId": "offline", "tenantId": "t1", "intent": "policy_qa",
        "usage": {"input_tokens": 0, "output_tokens": 0, "cost": None, "usage_complete": True},
    }])
    assert report["zeroUsageRuns"] == 1
    assert report["unattributedRuns"] == 0
    assert report["costComplete"] is True
    assert report["groups"] == []
    assert report["total"]["runs"] == 0


# ===== 查询端点 =====

def test_cost_endpoint_permissions_and_tenant_scope(database, monkeypatch):
    monkeypatch.setattr(settings, "llm_price_table", PRICE_TABLE)
    cost.reset()
    usage = _usage_with({"model": "priced-chat", "purpose": "policy.answer",
                         "input_tokens": 10, "output_tokens": 8})
    database.add(_run("default", usage, run_id="r-self"))
    database.add(_run("other-tenant", usage, run_id="r-other"))
    database.commit()

    with TestClient(app_main.app) as client:
        assert client.get("/api/agent/costs", headers=_headers("policy:read")).status_code == 403

        own = client.get("/api/agent/costs", headers=_headers("agent:audit"))
        assert own.status_code == 200
        body_own = own.json()
        assert body_own["window"]["tenant"] == "default"
        assert body_own["window"]["scope"] == "current-tenant"
        assert body_own["total"]["runs"] == 1
        assert body_own["costComplete"] is True
        assert body_own["total"]["cost"] == pytest.approx(0.000084)

        cross_without_admin = client.get(
            "/api/agent/costs?tenant=other-tenant", headers=_headers("agent:audit"),
        )
        assert cross_without_admin.status_code == 403

        cross = client.get(
            "/api/agent/costs?tenant=other-tenant&groupBy=tenant",
            headers=_headers("agent:audit,agent:admin"),
        )
        assert cross.status_code == 200
        assert cross.json()["window"]["scope"] == "cross-tenant"
        assert cross.json()["groups"][0]["tenant"] == "other-tenant"

        # 全平台口径只给平台管理员
        assert client.get(
            "/api/agent/costs?tenant=all-tenants", headers=_headers("agent:audit"),
        ).status_code == 403
        all_tenants = client.get(
            "/api/agent/costs?tenant=all-tenants&groupBy=tenant",
            headers=_headers("agent:audit,agent:admin"),
        )
        assert all_tenants.status_code == 200
        body_all = all_tenants.json()
        assert body_all["window"]["scope"] == "all-tenants"
        assert body_all["total"]["runs"] == 2
        assert {group["tenant"] for group in body_all["groups"]} == {"default", "other-tenant"}


def test_cost_endpoint_rejects_bad_query(database, monkeypatch):
    monkeypatch.setattr(settings, "cost_query_max_days", 30)
    with TestClient(app_main.app) as client:
        too_long = client.get("/api/agent/costs?days=90", headers=_headers("agent:audit"))
        assert too_long.status_code == 422
        assert "COST_QUERY_MAX_DAYS" in str(too_long.json()["detail"])
        bad_group = client.get("/api/agent/costs?groupBy=model,secret", headers=_headers("agent:audit"))
        assert bad_group.status_code == 422
        assert "secret" in str(bad_group.json()["detail"])


def test_cost_endpoint_reports_unknown_cost_as_null(database):
    usage = _usage_with({"model": "unknown-chat", "purpose": "policy.answer",
                         "input_tokens": 10, "output_tokens": 8})
    database.add(_run("default", usage, run_id="r-unknown"))
    database.commit()

    with TestClient(app_main.app) as client:
        body = client.get("/api/agent/costs", headers=_headers("agent:audit")).json()

    assert body["total"]["cost"] is None, "未定价模型不得给出任何金额"
    assert body["costComplete"] is False
    assert body["unpricedModels"] == ["unknown-chat"]
    assert body["unpricedReasons"] == [cost.REASON_MODEL_NOT_PRICED]
    assert "不得把 cost 当作完整账单" in body["note"]


def test_cost_endpoint_flags_truncated_window(database, monkeypatch):
    monkeypatch.setattr(settings, "cost_query_max_runs", 1)
    cost.reset()
    database.add(_run("default", {"input_tokens": 1, "output_tokens": 1}, run_id="r-1"))
    database.add(_run("default", {"input_tokens": 1, "output_tokens": 1}, run_id="r-2"))
    database.commit()

    with TestClient(app_main.app) as client:
        body = client.get("/api/agent/costs", headers=_headers("agent:audit")).json()

    assert body["truncated"] is True
    assert "COST_QUERY_MAX_RUNS" in body["truncateNote"]
    assert body["scannedRuns"] == 1


# ===== 端到端：模型调用 → AgentRun.usage =====

def test_policy_answer_persists_cost_per_model_and_purpose(database, monkeypatch):
    monkeypatch.setattr(settings, "llm_price_table", PRICE_TABLE)
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-not-used")
    cost.reset()

    class _Usage:
        prompt_tokens = 10
        completion_tokens = 8

    class _Message:
        content = '{"answer":"申请研发补助应提交研发费用归集表[引用1]。","usedCitations":[1]}'

    class _Choice:
        message = _Message()

    class _Response:
        usage = _Usage()
        choices = [_Choice()]

    monkeypatch.setattr(LLMClient, "_completion", lambda self, model, messages, temperature: _Response())
    create_policy_document(
        database, title="研发补助办法",
        content="第一条 企业申请研发补助应当提交研发费用归集表与营业执照复印件。",
    )
    database.commit()

    answer_policy(database, PolicyQuery(question="研发补助申请需要什么材料？"))

    run = database.query(AgentRun).filter(AgentRun.intent == "policy_qa").one()
    usage = run.usage
    assert usage["input_tokens"] == 10 and usage["output_tokens"] == 8
    assert usage["cost"] == pytest.approx(0.000084)
    assert usage["cost_complete"] is True and usage["unpriced_models"] == []
    bucket = usage["by_model"][settings.llm_model_generation]
    assert bucket["purposes"]["policy.answer"]["input_tokens"] == 10
    assert bucket["purposes"]["policy.answer"]["cost"] == pytest.approx(0.000084)
    # AgentRun 的 routing 与 usage 明细都必须落库，成本才可能按租户/功能/模型回溯
    assert run.routing["models"], "路由决策汇总也要落库"


def test_policy_answer_without_price_table_keeps_cost_null(database, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-not-used")
    cost.reset()

    class _Usage:
        prompt_tokens = 10
        completion_tokens = 8

    class _Message:
        content = '{"answer":"申请研发补助应提交研发费用归集表[引用1]。","usedCitations":[1]}'

    class _Choice:
        message = _Message()

    class _Response:
        usage = _Usage()
        choices = [_Choice()]

    monkeypatch.setattr(LLMClient, "_completion", lambda self, model, messages, temperature: _Response())
    create_policy_document(
        database, title="研发补助办法",
        content="第一条 企业申请研发补助应当提交研发费用归集表与营业执照复印件。",
    )
    database.commit()

    answer_policy(database, PolicyQuery(question="研发补助申请需要什么材料？"))

    run = database.query(AgentRun).filter(AgentRun.intent == "policy_qa").one()
    assert run.usage["cost"] is None
    assert run.usage["cost_complete"] is False
    assert run.usage["unpriced_models"] == [settings.llm_model_generation]


def test_chat_stream_records_usage_when_client_disconnects(monkeypatch):
    """SSE 中断（生成器被 close）也必须入账。

    否则这次调用在账面上完全消失，而落库的 usage 反而看起来"完整"。
    拿不到 usage 就按"用量未知"记一次调用（成本 null、暴露缺口）。
    """
    from app.agent.runtime import RunCapture, current_run

    class _Chunk:
        def __init__(self, content):
            delta = type("_Delta", (), {"content": content})()
            self.choices = [type("_Choice", (), {"delta": delta})()]
            self.usage = None

    class _Stream:
        def __iter__(self):
            yield _Chunk("第一段")
            yield _Chunk("第二段")
            raise AssertionError("客户端已断开，不应继续迭代")

    class _Completions:
        def create(self, **kwargs):
            return _Stream()

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(settings, "llm_api_key", "sk-test-not-used")
    client = LLMClient()
    monkeypatch.setattr(client, "_client", _Client())

    capture = RunCapture(intent="drafting")
    token = current_run.set(capture)
    try:
        stream = client.chat_stream([{"role": "user", "content": "写一段通知"}], model="flagship-x")
        assert next(stream) == "第一段"
        stream.close()
    finally:
        current_run.reset(token)

    bucket = capture.usage["by_model"]["flagship-x"]
    assert bucket["calls"] == 1
    assert bucket["cost"] is None
    assert bucket["unpriced_reasons"] == [cost.REASON_TOKEN_USAGE_MISSING]
    assert capture.usage["usage_complete"] is False