from __future__ import annotations

import json
import time
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db, main as app_main
from app.agent.models import AgentRun, DraftEvidence, DraftReview
from app.agent.registry import RetryableToolError, ToolDefinition, ToolError, ToolRegistry
from app.agent.review import assert_publishable, content_hash, evidence_fingerprint, review_draft
from app.agent.runtime import agent_run, context_call, current_run, snapshot, step
from app.config import settings
from app.models import Draft, FactCheck
from app.schemas import PolicyQuery
from app.services.factcheck import run_factcheck
from app.services.llm import LLMClient
from app.services.policy import answer_policy, create_policy_document, search_policy_clauses
from evals.metrics import retrieval_metrics


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine)
    app_db.Base.metadata.create_all(engine)
    for module in (app_db, app_main):
        monkeypatch.setattr(module, "engine", engine)
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    monkeypatch.setattr(settings, "rerank_url", "")
    monkeypatch.setattr(settings, "rerank_local_model", "")
    with factory() as db:
        yield db
    engine.dispose()


def test_policy_run_persists_evidence_and_steps(database):
    document = create_policy_document(database, title="测试补助办法", content="第一条 企业申请研发补助应提交年度审计报告。", effective_date=datetime(2026, 1, 1))
    answer = answer_policy(database, PolicyQuery(question="研发补助申请材料？", sessionId="session-1"))
    run = database.get(AgentRun, answer["runId"])
    assert run.status == "completed" and run.session_id == "session-1"
    assert run.verification_result["citation_ids"] == [document.clauses[0].id]
    names = {record["name"] for record in run.steps}
    assert {"retrieval.bm25", "retrieval.dense", "retrieval.rerank", "policy.answer"} <= names
    assert run.usage["cost"] is None


def test_failed_runs_are_persisted_after_business_rollback(database):
    @agent_run("failure-test")
    def fail(db):
        with step("failing-step"):
            db.rollback()
            raise ValueError("should not appear as sensitive error data")

    with pytest.raises(ValueError):
        fail(database)
    run = database.query(AgentRun).one()
    assert run.status == "failed" and run.error == "ValueError"
    assert run.steps[0]["status"] == "failed"
    assert current_run.get() is None


def test_thread_context_keeps_model_steps_in_parent_run(database):
    from concurrent.futures import ThreadPoolExecutor

    @agent_run("parallel")
    def execute(db):
        def worker():
            with step("parallel-model"):
                return current_run.get().run_id
        with ThreadPoolExecutor(max_workers=1) as executor:
            return {"child": executor.submit(context_call(worker)).result()}

    result = execute(database)
    assert result["child"] == result["runId"]
    assert database.get(AgentRun, result["runId"]).steps[0]["name"] == "parallel-model"


def test_temporal_region_industry_and_version_filters(database):
    from evals.run import seed_corpus
    mapping = seed_corpus(database)
    current = search_policy_clauses(database, "研发补助材料", region="测试市", as_of=datetime(2026, 10, 11))
    assert current and {mapping[row["clause"].id][0] for row in current} == {"rd-current"}
    previous = search_policy_clauses(database, "研发补助材料", region="测试市", as_of=datetime(2025, 6, 1))
    assert previous and {mapping[row["clause"].id][0] for row in previous} == {"rd-old"}
    assert not search_policy_clauses(database, "出口奖励", policy_name="测试出口奖励办法", as_of=datetime(2026, 10, 11))
    assert not search_policy_clauses(database, "研发补助", industry="制造", region="测试市")


def test_remote_reranker_reorders_and_failure_degrades(database, monkeypatch):
    from app.agent.retrieval import rerank
    create_policy_document(database, title="测试补助办法", content="第一条 企业申请研发补助应提交年度审计报告。\n第二条 企业应保留研发费用台账。")
    candidates = search_policy_clauses(database, "企业研发补助")
    monkeypatch.setattr(settings, "rerank_url", "https://reranker.invalid")
    monkeypatch.setattr(settings, "rerank_api_key", "test-rerank-key")

    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"results": [{"index": index, "relevance_score": index} for index in range(len(candidates))]}

    monkeypatch.setattr("app.agent.retrieval.httpx.post", lambda *a, **k: Response())
    ranked, info = rerank("企业研发补助", candidates)
    assert info["backend"] == "cross-encoder-api"
    assert ranked[0]["rerank_score"] == len(candidates) - 1

    monkeypatch.setattr("app.agent.retrieval.httpx.post", lambda *a, **k: (_ for _ in ()).throw(ValueError()))
    _, info = rerank("企业研发补助", candidates)
    assert info["degraded"] and info["backend"] == "deterministic-lexical"


def test_fact_mapping_rejects_scattered_numbers_and_omitted_claims(database):
    class OmitLLM:
        is_mock = False
        def chat_json(self, messages, **kwargs):
            return {"claims": []} if "抽取" in messages[0]["content"] else {"report": []}

    report = run_factcheck("测试公司利润增长50%。", [{"name": "收入", "value": "收入增长50%"}], "", OmitLLM())
    assert report and report[0]["status"] == "无法核实" and not report[0]["evidence"]


def reviewed_draft(db):
    draft = Draft(id="review-v1", title="测试稿件", content="测试公司收入为100万元。", status="审阅", created_by="author")
    db.add(draft)
    db.flush()
    db.add(FactCheck(draft_id=draft.id, claim="测试公司收入为100万元", status="一致", basis="用户原文"))
    db.add(DraftEvidence(
        draft_id=draft.id, claim="测试公司收入为100万元", status="一致",
        sources=[{"kind": "user_input", "excerpt": "测试公司收入为100万元", "sourceRef": "input:income"}],
        content_hash=content_hash(draft),
    ))
    db.commit()
    db.refresh(draft)
    return draft


def test_publish_requires_independent_human_review(database):
    draft = reviewed_draft(database)
    with pytest.raises(HTTPException):
        assert_publishable(database, draft)
    with pytest.raises(HTTPException) as error:
        review_draft(database, draft, "author", "approve", "同意")
    assert error.value.status_code == 403
    review_draft(database, draft, "reviewer", "approve", "已核对原始来源")
    assert_publishable(database, draft)
    draft.content += "内容发生变化。"
    with pytest.raises(HTTPException):
        assert_publishable(database, draft)


def test_evidence_changes_invalidate_review(database):
    draft = reviewed_draft(database)
    review_draft(database, draft, "reviewer", "approve", "已核验")
    record = database.query(DraftEvidence).one()
    record.sources = [{"kind": "material", "excerpt": "另一来源"}]
    database.commit()
    with pytest.raises(HTTPException):
        assert_publishable(database, draft)


def test_empty_fact_report_cannot_be_published(database):
    draft = Draft(id="empty-v1", content="无核验的内容", status="审阅")
    database.add(draft)
    database.commit()
    with pytest.raises(HTTPException):
        review_draft(database, draft, "reviewer", "approve", "同意")


def definition(**overrides):
    return ToolDefinition(
        name="echo", description="test",
        input_schema={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}, "additionalProperties": False},
        output_schema={"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}},
        permission="echo:read", **overrides,
    )


def test_registry_checks_permissions_schema_idempotency_and_output():
    registry = ToolRegistry(max_workers=1)
    registry.register(definition(idempotency="process_key"), lambda payload: payload)
    try:
        with pytest.raises(ToolError, match="permission"):
            registry.invoke("echo", {"text": "hello"}, permissions=set(), principal="u")
        with pytest.raises(ToolError) as error:
            registry.invoke("echo", {"text": 1}, permissions={"echo:read"}, principal="u")
        assert error.value.code == "INVALID_INPUT"
        result = registry.invoke("echo", {"text": "hello"}, permissions={"echo:read"}, principal="u", idempotency_key="k")
        assert registry.invoke("echo", {"text": "hello"}, permissions={"echo:read"}, principal="u", idempotency_key="k") == result
        with pytest.raises(ToolError) as error:
            registry.invoke("echo", {"text": "different"}, permissions={"echo:read"}, principal="u", idempotency_key="k")
        assert error.value.code == "IDEMPOTENCY_CONFLICT"
    finally:
        registry.executor.shutdown(wait=True)


def test_registry_timeout_is_bounded_and_transient_retry_is_explicit():
    registry = ToolRegistry(max_workers=1)
    registry.register(definition(timeout=0.01), lambda _: (time.sleep(0.05) or {"text": "late"}))
    try:
        with pytest.raises(ToolError) as error:
            registry.invoke("echo", {"text": "a"}, permissions={"echo:read"}, principal="u")
        assert error.value.code == "TOOL_TIMEOUT"
    finally:
        registry.executor.shutdown(wait=True)
    registry = ToolRegistry(max_workers=1)
    attempts = []
    def transient(payload):
        attempts.append(1)
        if len(attempts) == 1:
            raise RetryableToolError()
        return payload
    registry.register(definition(retry_policy={"max_attempts": 2}), transient)
    try:
        assert registry.invoke("echo", {"text": "a"}, permissions={"echo:read"}, principal="u") == {"text": "a"}
        assert len(attempts) == 2
    finally:
        registry.executor.shutdown(wait=True)


def test_agent_routes_reject_untrusted_identity_and_review(database):
    with TestClient(app_main.app) as client:
        assert client.get("/api/agent/registry").status_code == 403
        headers = {"X-Internal-Token": settings.ai_internal_token, "X-User-Id": "reviewer", "X-User-Permissions": "draft:review,agent:audit,policy:read"}
        assert client.get("/api/agent/registry", headers=headers).status_code == 200
        response = client.post("/api/agent/tools/search_policy/invoke", headers=headers, json={"input": {"question": "研发补助材料？"}})
        assert response.status_code == 200
        assert client.get(f"/api/agent/runs/{response.json()['runId']}", headers=headers).status_code == 200
        draft = reviewed_draft(database)
        denied = client.post(f"/api/drafts/{draft.id}/review", json={"decision": "approve", "comment": "同意"})
        assert denied.status_code == 403
        approved = client.post(f"/api/drafts/{draft.id}/review", headers=headers, json={"decision": "approve", "comment": "已核验"})
        assert approved.status_code == 200


def test_sync_and_stream_announcement_have_agent_runs(database, monkeypatch):
    import app.services.generation as generation
    monkeypatch.setattr(generation, "_style_guidelines", lambda _: "")
    with TestClient(app_main.app, headers={
        "X-Internal-Token": settings.ai_internal_token, "X-User-Id": "author",
        "X-User-Permissions": "draft:write",
    }) as client:
        payload = {"eventDesc": "测试公司于2026年10月11日召开项目启动会。", "template": "news_release"}
        response = client.post("/api/drafts/news", json=payload)
        assert response.status_code == 200
        run_id = response.json()["runId"]
        assert database.get(AgentRun, run_id).intent == "announcement"
        response = client.post("/api/drafts/news/stream", json=payload)
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        done = next(event for event in events if event["type"] == "done")
        assert database.get(AgentRun, done["runId"]).intent == "announcement_stream"


def test_metrics_and_secret_redaction():
    metrics = retrieval_metrics(["wrong", "right"], ["right"])
    assert metrics["recall_at_k"] == 1 and metrics["mrr"] == 0.5
    assert snapshot({"password": "secret", "nested": {"api_key": "secret"}}) == {"password": "[REDACTED]", "nested": {"api_key": "[REDACTED]"}}


def test_headings_and_bold_facts_are_not_skipped(database):
    from app.services.factcheck import _mock_extract_claims
    claims = _mock_extract_claims("# 测试公司收入为100万元\n**测试公司利润为50万元**。")
    assert claims == ["测试公司收入为100万元", "测试公司利润为50万元"]
    draft = reviewed_draft(database)
    draft.content += "\n# 测试公司利润为50万元"
    database.query(DraftEvidence).update({"content_hash": content_hash(draft)})
    database.commit()
    with pytest.raises(HTTPException):
        review_draft(database, draft, "reviewer", "approve", "已核验")


def test_missing_author_cannot_receive_approval(database):
    draft = reviewed_draft(database)
    draft.created_by = ""
    database.commit()
    with pytest.raises(HTTPException) as error:
        review_draft(database, draft, "reviewer", "approve", "同意")
    assert error.value.status_code == 422


def test_reverification_invalidates_existing_approval(database):
    from app.models import DraftElement
    draft = reviewed_draft(database)
    database.add(DraftElement(
        draft_id=draft.id, name="事实", value="测试公司收入为100万元",
        verified_status="已校验", source_ref="input:fact",
    ))
    database.commit()
    review_draft(database, draft, "reviewer", "approve", "已核验")
    headers = {
        "X-Internal-Token": settings.ai_internal_token, "X-User-Id": "author",
        "X-User-Permissions": "draft:verify",
    }
    with TestClient(app_main.app) as client:
        assert client.post(f"/api/drafts/{draft.id}/verify", headers=headers).status_code == 200
    database.expire_all()
    assert database.query(DraftReview).order_by(DraftReview.id.desc()).first().decision == "invalidated"
    with pytest.raises(HTTPException):
        assert_publishable(database, database.get(Draft, draft.id))


def test_review_list_requires_trusted_reviewer(database):
    with TestClient(app_main.app) as client:
        assert client.get("/api/drafts").status_code == 403
        headers = {
            "X-Internal-Token": settings.ai_internal_token, "X-User-Id": "author",
            "X-User-Permissions": "draft:write",
        }
        assert client.get("/api/drafts", headers=headers).status_code == 403
        headers["X-User-Permissions"] = "draft:review"
        assert client.get("/api/drafts", headers=headers).status_code == 200
        assert client.get("/api/drafts?limit=101", headers=headers).status_code == 422


def test_duplicate_remote_rerank_indexes_trigger_degradation(database, monkeypatch):
    from app.agent.retrieval import rerank
    create_policy_document(database, title="测试补助", content="第一条 企业申请研发补助应提交年度审计报告。\n第二条 企业应保留研发费用台账。")
    candidates = search_policy_clauses(database, "企业研发补助")
    monkeypatch.setattr(settings, "rerank_url", "https://reranker.invalid")
    monkeypatch.setattr(settings, "rerank_api_key", "test-rerank-key")
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"results": [{"index": 0, "relevance_score": 1} for _ in candidates]}
    monkeypatch.setattr("app.agent.retrieval.httpx.post", lambda *a, **k: Response())
    _, info = rerank("企业研发补助", candidates)
    assert info["degraded"]


def test_registered_generation_and_export_are_idempotent(database, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "export_dir", str(tmp_path))
    headers = {
        "X-Internal-Token": settings.ai_internal_token, "X-User-Id": "tool-author",
        "X-User-Permissions": "draft:write",
    }
    with TestClient(app_main.app) as client:
        payload = {"input": {"eventDesc": "测试公司于2026年10月11日召开会议。", "template": "news_release"}, "idempotencyKey": "generation-regression"}
        response = client.post("/api/agent/tools/generate_announcement/invoke", json=payload, headers=headers)
        assert response.status_code == 200, response.text
        draft_id = response.json()["output"]["versionId"]
        repeated = client.post("/api/agent/tools/generate_announcement/invoke", json=payload, headers=headers)
        assert repeated.json()["output"]["versionId"] == draft_id
        exported = client.post("/api/agent/tools/export_word_document/invoke", json={
            "input": {"draftId": draft_id}, "idempotencyKey": "export-regression",
        }, headers=headers)
        assert exported.status_code == 200, exported.text
        assert exported.json()["output"]["format"] == "docx"


def test_generation_releases_read_transaction_before_graph(database, monkeypatch):
    from app.models import Template
    from app.routers.drafts import generate_news
    from app.schemas import GenerateRequest
    template = Template(name="transaction-test", category="news", schema_={"sections": []}, is_active=True)
    database.add(template)
    database.commit()
    class Graph:
        def invoke(self, state):
            assert not database.in_transaction()
            return {"drafts": [{"style": "正式", "content": "# 测试\n测试公司召开会议。"}]}
    monkeypatch.setattr("app.graphs.drafting.build_draft_graph", lambda _: Graph())
    result = generate_news(GenerateRequest(template="transaction-test", eventDesc="测试公司召开会议。"), database)
    assert result.versionId


def test_answer_rejects_undeclared_citation_numbers():
    from app.services.policy import _llm_answer
    class InvalidReferences:
        is_mock = False
        def chat_json(self, *args, **kwargs):
            return {"answer": "测试结论[引用1]。无依据结论[引用99]。", "usedCitations": [1]}
    citations = [{"docTitle": "测试办法", "articleNo": "第一条", "excerpt": "应提交审计报告"}]
    answer, flags = _llm_answer("需要什么材料？", citations, InvalidReferences())
    assert flags and "[引用99]" not in answer


def test_revision_author_is_editor_not_original_author(database):
    from app.observability import user_id_var
    from app.services.revise import persist_revision
    draft = reviewed_draft(database)
    token = user_id_var.set("editor")
    try:
        edited = persist_revision(database, draft, draft.content, "编辑", [])
        assert edited.created_by == "editor"
    finally:
        user_id_var.reset(token)


def test_publication_requires_trusted_writer_identity(database):
    draft = reviewed_draft(database)
    review_draft(database, draft, "reviewer", "approve", "已核验")
    with TestClient(app_main.app) as client:
        assert client.post(f"/api/drafts/{draft.id}/status", json={"status": "发布"}).status_code == 403
        headers = {
            "X-Internal-Token": settings.ai_internal_token, "X-User-Id": "author",
            "X-User-Permissions": "draft:write",
        }
        response = client.post(f"/api/drafts/{draft.id}/status", headers=headers, json={"status": "发布"})
        assert response.status_code == 200 and response.json()["status"] == "发布"
