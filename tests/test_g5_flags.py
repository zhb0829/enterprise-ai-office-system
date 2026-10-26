"""G5 运行时降级开关：热切换、降级留痕与权限边界。

口径：关闭开关必须"服务仍正常返回 + 明确标记降级"，不允许静默关闭或伪造成功。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import main as app_main
from app.agent import runtime_flags
from app.agent.platform_models import GovernanceAudit
from app.config import settings
from app.schemas import PolicyQuery
from app.services.factcheck import run_factcheck
from app.services.llm import LLMClient, LLMError
from app.services.materials import EmbeddingError, embed_texts
from app.services.policy import answer_policy, create_policy_document


@pytest.fixture(autouse=True)
def isolated_flags():
    """开关是进程级状态：每个用例前后复位，避免污染其他测试。"""
    runtime_flags.reset()
    yield
    runtime_flags.reset()


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


def _headers(permissions: str) -> dict:
    return {
        "X-Internal-Token": settings.ai_internal_token,
        "X-User-Id": "ops-user", "X-Tenant-Id": "default",
        "X-User-Permissions": permissions,
    }


def _candidates() -> list[dict]:
    rows = []
    for index, text in enumerate(["研发费用归集表是申请材料之一", "申报材料需要加盖公章"]):
        rows.append({
            "clause": SimpleNamespace(id=index + 1, content=text),
            "document": SimpleNamespace(title=f"政策{index + 1}"),
            "rrf_score": round(0.5 - index * 0.1, 4),
        })
    return rows


# ===== 开关状态机 =====

def test_flag_override_and_restore(monkeypatch):
    monkeypatch.setattr(settings, "kg_enabled", False)
    assert runtime_flags.enabled("kg") is False
    state = runtime_flags.set_flag("kg", True, operator="ops", reason="故障演练")
    assert state["enabled"] is True and state["changed"] is True
    assert state["source"] == "runtime-override"
    restored = runtime_flags.set_flag("kg", None, operator="ops", reason="恢复")
    assert restored["enabled"] is False and restored["source"] == "configuration"
    assert restored["changed"] is True


def test_unknown_flag_is_rejected():
    with pytest.raises(KeyError):
        runtime_flags.set_flag("not-a-flag", True)


# ===== 管理端点与权限边界 =====

def test_flag_endpoint_requires_audit_and_admin(database):
    with TestClient(app_main.app) as client:
        assert client.get("/api/agent/flags", headers=_headers("policy:read")).status_code == 403
        denied = client.put("/api/agent/flags/kg", json={"enabled": True}, headers=_headers("agent:audit"))
        assert denied.status_code == 403
        ok = client.put(
            "/api/agent/flags/kg",
            json={"enabled": True, "reason": "对客演练"},
            headers=_headers("agent:admin"),
        )
        assert ok.status_code == 200
        assert ok.json()["enabled"] is True
        assert client.put(
            "/api/agent/flags/unknown", json={"enabled": True}, headers=_headers("agent:admin")
        ).status_code == 404
        listed = client.get("/api/agent/flags", headers=_headers("agent:audit"))
        assert listed.status_code == 200
        assert listed.json()["flags"]["kg"]["enabled"] is True

    audit_rows = database.query(GovernanceAudit).filter(GovernanceAudit.action == "flag.update").all()
    assert len(audit_rows) == 1
    assert audit_rows[0].details["enabled"] is True
    assert audit_rows[0].details["reason"] == "对客演练"


# ===== 关闭外部模型：服务仍返回，且标记降级 =====

def test_remote_llm_flag_switches_client_to_mock(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-not-used")
    client = LLMClient()
    assert client.is_mock is False
    runtime_flags.set_flag("remote_llm", False, operator="ops", reason="模拟外部模型故障")
    assert client.is_mock is True
    with pytest.raises(LLMError):
        client.chat([{"role": "user", "content": "你好"}])


def test_remote_embedding_flag_refuses_hash_substitution(monkeypatch):
    monkeypatch.setattr(settings, "embedding_api_key", "sk-test-not-used")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-3-small")
    runtime_flags.set_flag("remote_embedding", False, operator="ops", reason="模拟向量服务故障")
    with pytest.raises(EmbeddingError):
        embed_texts(["研发费用归集要求"])
    # 未配置真实服务时仍走本地哈希兜底（离线口径不受开关影响）
    monkeypatch.setattr(settings, "embedding_api_key", "")
    assert embed_texts(["研发费用归集要求"])


def test_semantic_rerank_flag_degrades_to_lexical(monkeypatch):
    from app.agent.retrieval import rerank

    monkeypatch.setattr(settings, "rerank_url", "https://rerank.invalid/v1/rerank")
    monkeypatch.setattr(settings, "rerank_api_key", "test-key")
    runtime_flags.set_flag("semantic_rerank", False, operator="ops", reason="模拟精排服务故障")
    ranked, diagnostics = rerank("研发费用", _candidates())
    assert diagnostics["backend"] == "deterministic-lexical"
    assert diagnostics["degraded"] is True
    assert diagnostics["reason"] == "runtime-flag-semantic-rerank-off"
    assert ranked and all("score" in row for row in ranked)


def test_policy_answer_survives_flag_outages(database, monkeypatch):
    create_policy_document(
        database, title="研发补助办法",
        content="第一条 企业申请研发补助应当提交研发费用归集表与营业执照复印件。",
        industry_tags=["科技"],
    )
    database.commit()
    # 配置齐全但被开关关闭：必须"停在开关上"，不能去连远端（也不能混用哈希向量）
    monkeypatch.setattr(settings, "embedding_api_key", "sk-test-not-used")
    monkeypatch.setattr(settings, "llm_api_key", "sk-test-not-used")
    runtime_flags.set_flag("remote_embedding", False, operator="ops", reason="演练")
    runtime_flags.set_flag("remote_llm", False, operator="ops", reason="演练")

    result = answer_policy(database, PolicyQuery(question="研发补助申请需要什么材料？"))

    assert result["answer"]
    assert result["clauses"], "关闭外部模型后仍应返回检索到的条款"
    assert result["degraded"] is True
    reasons = " ".join(result["degradationReasons"])
    assert "运行时开关" in reasons
    retrieval = result["retrieval"][0]
    assert retrieval["denseBackend"] == "disabled-by-flag"
    assert retrieval["denseDisabled"] is True
    assert "remote_embedding" in retrieval["runtimeFlags"]


def test_kg_flag_disables_graph_source(database, monkeypatch):
    create_policy_document(
        database, title="条例",
        content="第一条 企业应当建立研发费用辅助账。",
    )
    database.commit()
    monkeypatch.setattr(settings, "kg_enabled", True)
    runtime_flags.set_flag("kg", False, operator="ops", reason="模拟图库故障")
    result = answer_policy(database, PolicyQuery(question="研发费用辅助账怎么建？"))
    first = result["retrieval"][0]
    assert "graph" not in first["fusionSources"]
    assert first["graph"]["enabled"] is False
    assert "图谱召回已被运行时开关关闭" in " ".join(result["degradationReasons"])
    assert "kg" in first["runtimeFlags"]


# ===== 交叉验证（事实核查）开关 =====

def test_factcheck_flag_marks_rule_based_fallback(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    runtime_flags.set_flag("factcheck", False, operator="ops", reason="模拟核查模型故障")
    report = run_factcheck(
        "公司于2026年10月11日召开项目启动会。",
        [{"name": "发布日期", "value": "2026年10月11日"}], "",
        LLMClient(),
    )
    assert report
    assert all(item.get("degraded") is True for item in report)
    assert all(item["degradeReason"] == "runtime-flag-factcheck-off" for item in report)
    assert all(item["status"] in {"一致", "不一致", "无法核实"} for item in report)