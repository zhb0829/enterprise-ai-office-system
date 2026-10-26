"""G4 模型分层路由：复杂度判定、层选择、回落与审计留痕。

口径：不路由时必须能说清为什么（`source` + `reason`），路由后必须能从 AgentRun 回溯
"这次为什么用了这个模型"；未配置轻量层 / 旗舰层时开启路由是 no-op，不允许假装路由过。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import main as app_main
from app.agent import runtime_flags
from app.agent.models import AgentRun
from app.config import Settings, settings
from app.schemas import PolicyQuery
from app.services import cost, model_router
from app.services.llm import LLMClient
from app.services.policy import answer_policy, create_policy_document

SIMPLE_QUESTION = "研发补助申请需要什么材料？"
COMPLEX_QUESTION = (
    "研发补助申请需要提交什么材料，如果同时申报市级和区级补助，"
    "两个渠道的要求分别有哪些差异，是否存在冲突，为什么？"
)


@pytest.fixture(autouse=True)
def isolated_routing_state():
    """路由开关与价格表都是进程级状态：每个用例前后复位。"""
    runtime_flags.reset()
    cost.reset()
    yield
    runtime_flags.reset()
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
    with factory() as db:
        yield db
    engine.dispose()


def _enable_routing(monkeypatch, *, light="tier-light-chat", reasoning="tier-reasoning-chat",
                    standard="tier-standard-chat") -> None:
    monkeypatch.setattr(settings, "llm_routing_enabled", True)
    monkeypatch.setattr(settings, "llm_routing_light_max_score", 0)
    monkeypatch.setattr(settings, "llm_routing_reasoning_min_score", 3)
    monkeypatch.setattr(settings, "llm_model_tier_light", light)
    monkeypatch.setattr(settings, "llm_model_tier_standard", standard)
    monkeypatch.setattr(settings, "llm_model_tier_reasoning", reasoning)


def _fake_completion(content: str, *, prompt_tokens=10, completion_tokens=8):
    """替身外部调用：只替换 `_completion`，其余（路由、审计、成本、落库）走真实代码。"""

    class _Usage:
        pass

    class _Message:
        pass

    class _Choice:
        pass

    class _Response:
        pass

    usage = _Usage()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    message = _Message()
    message.content = content
    choice = _Choice()
    choice.message = message
    response = _Response()
    response.usage = usage
    response.choices = [choice]
    return lambda self, model, messages, temperature: response


# ===== 复杂度判定 =====

def test_complexity_scoring_is_explainable():
    simple_score, simple_signals = model_router.score_complexity(SIMPLE_QUESTION, purpose="policy.answer")
    assert simple_score <= 0, simple_signals
    assert simple_signals, "打分必须给出可读信号，便于回溯"
    assert model_router.complexity_for(simple_score) == model_router.COMPLEXITY_SIMPLE
    assert model_router.tier_for_score(simple_score) == model_router.TIER_LIGHT

    complex_score, complex_signals = model_router.score_complexity(
        COMPLEX_QUESTION, purpose="policy.answer", citation_count=8, context_chars=4000,
    )
    assert complex_score >= settings.llm_routing_reasoning_min_score, complex_signals
    assert any("reasoning-markers" in signal for signal in complex_signals)
    assert any("citations" in signal for signal in complex_signals)
    assert model_router.tier_for_score(complex_score) == model_router.TIER_REASONING


def test_moderate_complexity_uses_standard_tier():
    score, _ = model_router.score_complexity(
        "企业申请研发补助时提交的研发费用归集表，应当由哪个部门在多少个工作日内完成审核确认？",
        purpose="policy.answer",
    )
    assert model_router.complexity_for(score) == model_router.COMPLEXITY_MODERATE
    assert model_router.tier_for_score(score) == model_router.TIER_STANDARD


def test_threshold_overlap_is_rejected_at_config_load():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="test", llm_routing_light_max_score=3, llm_routing_reasoning_min_score=3)


# ===== 决策与回落 =====

def test_routing_disabled_keeps_configured_model(monkeypatch):
    monkeypatch.setattr(settings, "llm_routing_enabled", False)
    monkeypatch.setattr(settings, "llm_model_tier_light", "tier-light-chat")
    decision = model_router.decide(purpose="policy.answer", text=SIMPLE_QUESTION)
    assert decision.source == "routing-disabled"
    assert decision.model == settings.llm_model_generation
    assert decision.routed is False and decision.changed is False
    assert "未启用" in decision.reason


def test_routing_selects_tier_by_complexity(monkeypatch):
    _enable_routing(monkeypatch)
    simple = model_router.decide(purpose="policy.answer", text=SIMPLE_QUESTION)
    assert simple.tier == model_router.TIER_LIGHT
    assert simple.model == "tier-light-chat"
    assert simple.source == "complexity-simple" and simple.routed is True and simple.changed is True

    complex_decision = model_router.decide(purpose="policy.answer", text=COMPLEX_QUESTION)
    assert complex_decision.tier == model_router.TIER_REASONING
    assert complex_decision.model == "tier-reasoning-chat"
    assert complex_decision.source == "complexity-complex"


def test_unconfigured_tier_falls_back_and_explains(monkeypatch):
    _enable_routing(monkeypatch, light="")
    decision = model_router.decide(purpose="policy.answer", text=SIMPLE_QUESTION)
    assert decision.tier == model_router.TIER_LIGHT
    assert decision.model == "tier-standard-chat", "轻量层未配置时必须回落标准层"
    assert decision.source == "tier-model-unset"
    assert decision.routed is False
    assert "LLM_MODEL_TIER_LIGHT 未配置" in decision.reason


def test_explicit_model_is_never_overridden(monkeypatch):
    _enable_routing(monkeypatch)
    decision = model_router.decide(purpose="extraction", text=SIMPLE_QUESTION, model="extract-model")
    assert decision.model == "extract-model"
    assert decision.source == "explicit-model"
    assert decision.routed is False


def test_designated_purpose_is_never_routed(monkeypatch):
    """专用模型配置被置空（等价于没传 model）时，抽取/核查也不允许被分层接管。"""
    _enable_routing(monkeypatch)
    decision = model_router.decide(purpose="extraction", text=SIMPLE_QUESTION, model="")
    assert decision.source == "designated-purpose"
    assert decision.model == "tier-standard-chat"
    assert decision.routed is False and decision.changed is False
    assert "LLM_MODEL_EXTRACTION" in decision.reason


def test_unknown_purpose_is_conservative(monkeypatch):
    _enable_routing(monkeypatch)
    decision = model_router.decide(purpose="some.new.purpose", text=SIMPLE_QUESTION)
    assert decision.source == "purpose-not-routable"
    assert decision.model == "tier-standard-chat"


def test_runtime_flag_overrides_configuration(monkeypatch):
    _enable_routing(monkeypatch)
    assert model_router.decide(purpose="policy.answer", text=SIMPLE_QUESTION).tier == model_router.TIER_LIGHT
    runtime_flags.set_flag("model_routing", False, operator="ops", reason="演练")
    disabled = model_router.decide(purpose="policy.answer", text=SIMPLE_QUESTION)
    assert disabled.source == "routing-disabled"
    assert disabled.model == "tier-standard-chat"
    runtime_flags.set_flag("model_routing", None, operator="ops", reason="恢复")
    assert model_router.decide(purpose="policy.answer", text=SIMPLE_QUESTION).tier == model_router.TIER_LIGHT


# ===== 端到端：策略问答的路由与审计 =====

def test_policy_answer_routes_and_audits(database, monkeypatch):
    _enable_routing(monkeypatch)
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-not-used")
    monkeypatch.setattr(
        LLMClient, "_completion",
        _fake_completion('{"answer":"申请研发补助应提交研发费用归集表[引用1]。","usedCitations":[1]}'),
    )
    create_policy_document(
        database, title="研发补助办法",
        content="第一条 企业申请研发补助应当提交研发费用归集表与营业执照复印件。",
        industry_tags=["科技"],
    )
    database.commit()

    result = answer_policy(database, PolicyQuery(question=SIMPLE_QUESTION))

    assert result["clauses"], "必须有检索命中，才轮到生成模型"
    assert result["model"] == "tier-light-chat", f"简单问题应走轻量层，实际 {result['model']}"
    routing = result["routing"]
    assert routing is not None and routing["tier"] == model_router.TIER_LIGHT
    assert routing["purpose"] == "policy.answer" and routing["signals"]

    run = database.query(AgentRun).filter(AgentRun.intent == "policy_qa").one()
    assert run.routing["tiers"] == {"light": 1}
    assert run.routing["models"] == {"tier-light-chat": 1}
    assert run.routing["routedCalls"] == 1
    assert run.routing["enabled"] is True
    route_steps = [step for step in run.steps if step["name"] == "model.route"]
    assert len(route_steps) == 1
    assert route_steps[0]["model"] == "tier-light-chat"
    assert route_steps[0]["output"]["source"] == "complexity-simple"
    # 模型步骤也必须记下实际使用的层模型，而不是配置默认值
    answer_steps = [step for step in run.steps if step["name"] == "policy.answer"]
    assert answer_steps and answer_steps[0]["model"] == "tier-light-chat"
    assert any(step["name"] == "model.chat" and step["model"] == "tier-light-chat" for step in run.steps)


def test_policy_answer_complex_question_uses_reasoning_tier(database, monkeypatch):
    _enable_routing(monkeypatch)
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-not-used")
    monkeypatch.setattr(
        LLMClient, "_completion",
        _fake_completion('{"answer":"两类补助存在申报冲突，需按市级规定顺序申报[引用1]。","usedCitations":[1]}'),
    )
    create_policy_document(
        database, title="研发补助办法",
        content="第一条 企业申请研发补助应当提交研发费用归集表；同一项目不得重复享受市级与区级补助。",
        industry_tags=["科技"],
    )
    database.commit()

    result = answer_policy(database, PolicyQuery(question=COMPLEX_QUESTION))

    assert result["model"] == "tier-reasoning-chat"
    assert result["routing"]["tier"] == model_router.TIER_REASONING
    run = database.query(AgentRun).filter(AgentRun.intent == "policy_qa").one()
    assert run.routing["tiers"] == {"reasoning": 1}


def test_policy_answer_without_routing_reports_no_decision(database, monkeypatch):
    monkeypatch.setattr(settings, "llm_routing_enabled", False)
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-not-used")
    monkeypatch.setattr(
        LLMClient, "_completion",
        _fake_completion('{"answer":"申请研发补助应提交研发费用归集表[引用1]。","usedCitations":[1]}'),
    )
    create_policy_document(
        database, title="研发补助办法",
        content="第一条 企业申请研发补助应当提交研发费用归集表与营业执照复印件。",
    )
    database.commit()

    result = answer_policy(database, PolicyQuery(question=SIMPLE_QUESTION))

    assert result["model"] == settings.llm_model_tier_standard or result["model"] == settings.llm_model_generation
    assert result["routing"]["source"] == "routing-disabled"


# ===== 运维端点 =====

def test_model_routing_endpoint_requires_audit(database):
    def headers(permissions: str) -> dict:
        return {
            "X-Internal-Token": settings.ai_internal_token,
            "X-User-Id": "ops-user", "X-Tenant-Id": "default",
            "X-User-Permissions": permissions,
        }

    with TestClient(app_main.app) as client:
        assert client.get("/api/agent/model-routing", headers=headers("policy:read")).status_code == 403
        response = client.get("/api/agent/model-routing", headers=headers("agent:audit"))
        assert response.status_code == 200
        body = response.json()
        assert body["enabled"] is False
        assert set(body["tiers"]) == {"light", "standard", "reasoning"}
        assert body["thresholds"]["reasoningMinScore"] > body["thresholds"]["lightMaxScore"]
        assert "policy.answer" in body["routablePurposes"]


def test_model_router_snapshot_flags_unconfigured_tiers(monkeypatch):
    _enable_routing(monkeypatch, light="", reasoning="")
    snapshot = model_router.snapshot()
    assert snapshot["tiers"]["light"]["configured"] is False
    assert snapshot["tiers"]["standard"]["configured"] is True
    assert "no-op" in snapshot["note"]


def test_routing_summary_is_bounded(monkeypatch):
    """决策明细必须有上限：一次运行里同一用途被调用上千次时不允许把审计撑爆。"""
    from app.agent.runtime import RunCapture, current_run

    _enable_routing(monkeypatch)
    capture = RunCapture(intent="policy_qa")
    token = current_run.set(capture)
    try:
        for _ in range(model_router.MAX_DECISIONS + 10):
            model_router.resolve(purpose="policy.answer", text=SIMPLE_QUESTION)
    finally:
        current_run.reset(token)
    assert len(capture.routing["decisions"]) == model_router.MAX_DECISIONS
    assert capture.routing["tiers"]["light"] == model_router.MAX_DECISIONS + 10
    route_steps = [step for step in capture.steps if step["name"] == "model.route"]
    assert len(route_steps) == model_router.MAX_DECISIONS, "超过上限后不得再逐条写 step"