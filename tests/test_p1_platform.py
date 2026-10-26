from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db, main as app_main
from app.agent.governance import DataLevel, Principal, data_level_var, governed_get, model_messages, principal_var, redact, utcnow
from app.agent.knowledge import KnowledgeStore, search_knowledge
from app.agent.memory import MemoryStore, purge_expired
from app.agent.models import AgentRun
from app.agent.platform_models import GovernanceAudit, KnowledgeRelease, MemoryRecord
from app.agent.roles import AgentPipeline, EvidenceVerifier, FunctionActor, FunctionRetriever, TaskContext, WorkflowPlanner
from app.agent.runtime import agent_run
from app.config import settings
from app.models import ReferenceMaterial
from app.schemas import PolicyQuery
from app.services.policy import answer_policy, create_policy_document


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


def identity(user="u1", tenant="t1", department="d1", public_only=False):
    return Principal(user, tenant, department, frozenset({
        "memory:read", "memory:write", "memory:department:write", "memory:tenant:write",
        "policy:read", "draft:write", "knowledge:read", "knowledge:write", "knowledge:publish",
        "agent:audit", "agent:admin", "materials:read", "materials:write",
    }), DataLevel.internal, public_only)


@contextmanager
def as_identity(p):
    token = principal_var.set(p)
    data_token = data_level_var.set(DataLevel.public)
    try:
        yield
    finally:
        principal_var.reset(token)
        data_level_var.reset(data_token)


def headers(user="u1", tenant="t1", department="d1"):
    p = identity(user, tenant, department)
    return {
        "X-Internal-Token": settings.ai_internal_token, "X-User-Id": user, "X-Tenant-Id": tenant,
        "X-Department-Id": department, "X-User-Permissions": ",".join(p.permissions),
    }


def test_memory_isolated_expiring_conflict_redacted_and_deleted(database):
    with as_identity(identity()):
        store = MemoryStore(database)
        record = store.put("style", {"style": "formal", "email": "a@example.com"})
        database.commit()
        assert "a@example.com" not in str(record.value)
        with pytest.raises(HTTPException) as error:
            store.put("style", {"style": "short"}, expected_revision=0)
        assert error.value.status_code == 409
        store.put("style", {"style": "short"}, expected_revision=1)
        database.commit()
        assert store.read()[0].revision == 2
    for p in (identity("u2"), identity(tenant="t2"), identity(department="d2"), identity(public_only=True)):
        with as_identity(p):
            assert MemoryStore(database).read() == []
    with as_identity(identity()):
        store.delete(record.id)
        database.commit()
        expired = store.put("expired", {"value": "old"})
        expired.expires_at = utcnow() - timedelta(seconds=1)
        database.commit()
        assert store.read() == []
        assert purge_expired(database) == 1
        database.commit()


def test_shared_memory_scope_and_session_summary(database):
    with as_identity(identity()):
        store = MemoryStore(database)
        store.put("organization", {"name": "department-A"}, scope="department")
        store.put("tenant_style", {"name": "tenant-A"}, scope="tenant")
        for i in range(9):
            store.remember_turn("chat", f"question-{i}", f"answer-{i}", window=3)
        database.commit()
        context = store.context("chat")
        assert len(context["turns"]) == 3
        assert "question-0" in context["summary"] and "answer-5" in context["summary"]
        assert MemoryStore(database).context("another-chat")["turns"] == []
        assert store.clear_session("chat") == 2
        database.commit()
    with as_identity(identity("u2")):
        assert MemoryStore(database).read(scope="department")[0].value["name"] == "department-A"
    with as_identity(identity("u2", department="d2")):
        assert not MemoryStore(database).read(scope="department")
        assert MemoryStore(database).read(scope="tenant")[0].value["name"] == "tenant-A"


def doc(key="a", text="研发补助需要提交年度审计报告。"):
    return {"key": key, "text": text, "classification": "public"}


def publish(store, docs, **kwargs):
    row = store.stage(docs, **kwargs)
    store.publish(row.id)
    store.db.commit()
    return row


def test_incremental_index_reuses_vectors_and_hot_loads(database, monkeypatch):
    import app.services.materials as materials
    calls = []
    original = materials.embed_texts
    monkeypatch.setattr(materials, "embed_texts", lambda texts: (calls.append(list(texts)) or original(texts)))
    store = KnowledgeStore(database, "public:policy")
    first = publish(store, [doc("a"), doc("b", "企业应保留研发费用台账。")])
    snapshot = store.snapshot()
    assert snapshot["version"] == first.version and len(snapshot["entries"]) == 2
    second = publish(store, [doc("a"), doc("c", "研发补助需要提交税务证明。")], deleted_keys=["b"])
    assert second.changes["unchanged"] == 1 and second.changes["added"] == 1 and second.changes["deleted"] == 1
    assert len(calls) == 3
    assert {item["key"] for item in snapshot["entries"]} == {"a", "b"}
    reader = KnowledgeStore(database, "public:policy")
    assert {item["key"] for item in reader.snapshot()["entries"]} == {"a", "c"}
    snapshot["entries"][0]["chunks"][0]["text"] = "caller mutation"
    assert "caller mutation" not in str(reader.snapshot())
    rolled = store.rollback(first.id)
    database.commit()
    assert rolled.version > second.version
    assert {r["key"] for r in reader.snapshot()["entries"]} == {"a", "b"}


def test_scheduled_validity_and_publish_conflict(database):
    store = KnowledgeStore(database, "public:policy")
    now = utcnow()
    first = publish(store, [doc()], effective_at=now - timedelta(days=1))
    planned = publish(store, [doc("b")], effective_at=now + timedelta(days=1), expires_at=now + timedelta(days=2))
    assert store.snapshot(now)["version"] == first.version
    assert store.snapshot(now + timedelta(days=1, minutes=1))["version"] == planned.version
    assert store.snapshot(now + timedelta(days=3))["version"] == first.version
    stale = store.stage([doc("c")])
    other = store.stage([doc("d")])
    with pytest.raises(HTTPException) as error:
        store.publish(other.id)
    assert error.value.status_code == 409
    planned.status = "cancelled"
    store.publish(other.id)
    database.commit()
    with pytest.raises(HTTPException) as error:
        store.publish(stale.id)
    assert error.value.status_code == 409


def test_private_knowledge_isolated_and_public_import_rejected(database):
    with as_identity(identity()):
        store = KnowledgeStore(database, "tenant:t1:materials")
        publish(store, [{"key": "internal", "text": "企业内部的研发补助方案。", "classification": "internal",
                         "tenant_id": "t1", "department_id": "d1", "owner_id": "u1"}])
        assert store.snapshot()["entries"]
        assert search_knowledge(database, "materials", "研发补助方案")
    for p in (identity("u2"), identity(tenant="t2"), identity(department="d2"), identity(public_only=True)):
        with as_identity(p):
            assert not store.snapshot()["entries"]
    with pytest.raises(HTTPException):
        KnowledgeStore(database, "public:materials").stage([{
            "key": "private", "text": "private", "classification": "internal", "tenant_id": "t1",
        }])
    database.rollback()


def test_policy_actual_pipeline_captures_roles_version_memory_and_summary(database):
    with as_identity(identity()):
        create_policy_document(database, title="研发补助办法", content="第一条 企业申请研发补助应提交年度审计报告。")
        MemoryStore(database).put("style", {"style": "concise"})
        database.commit()
        response = answer_policy(database, PolicyQuery(question="研发补助申请材料？", sessionId="chat"))
        run = database.get(AgentRun, response["runId"])
        assert run.tenant_id == "t1" and run.department_id == "d1"
        assert run.plan == ["planner", "retriever", "actor", "verifier"]
        assert {s["name"] for s in run.steps} >= set(run.plan)
        assert run.verification_result["passed"]
        assert response["clauses"][0]["knowledgeVersion"] == 1
        assert MemoryStore(database).context("chat")["turns"][0]["question"] == "研发补助申请材料？"


def test_verifier_failure_never_returns_an_actor_result(database):
    @agent_run("test")
    def execute(db):
        pipeline = AgentPipeline(
            WorkflowPlanner(required_fields=("question",)), FunctionRetriever(lambda _: []),
            FunctionActor(lambda context, evidence: {"answer": "unsupported"}),
            EvidenceVerifier(lambda *args: {"passed": False, "reason": "no evidence"}),
        )
        return pipeline.execute(TaskContext("test", {"question": "test"}))
    with pytest.raises(HTTPException):
        execute(database)
    run = database.query(AgentRun).one()
    assert run.status == "failed"
    assert run.steps[-1]["name"] == "verifier" and run.steps[-1]["status"] == "failed"


def test_routes_reject_forged_identity_and_cross_tenant_audit(database):
    with TestClient(app_main.app) as client:
        forged = {"X-User-Id": "u1", "X-Tenant-Id": "t1", "X-User-Permissions": "memory:read"}
        assert client.get("/api/agent/memory", headers=forged).status_code == 403
        assert client.post("/api/drafts/news", json={"eventDesc": "test"}).status_code == 403
        created = client.put("/api/agent/memory", headers=headers(), json={"key": "style", "value": {"name": "concise"}})
        assert created.status_code == 200, created.text
        assert not client.get("/api/agent/memory", headers=headers(tenant="t2")).json()
        denied = client.delete(f"/api/agent/memory/{created.json()['id']}", headers=headers(tenant="t2"))
        assert denied.status_code == 404
        assert client.get("/api/agent/governance/audit", headers=headers()).json()
        cross = client.get("/api/agent/governance/audit", headers=headers(tenant="t2")).json()
        assert all(r["action"] in {"memory.read", "http.get", "http.delete"} for r in cross)


def test_orm_tenant_department_owner_and_public_isolation(database):
    database.add_all([
        ReferenceMaterial(filename="one", tenant_id="t1", department_id="d1", owner_id="u1", classification="internal"),
        ReferenceMaterial(filename="other-tenant", tenant_id="t2", classification="internal"),
        ReferenceMaterial(filename="other-department", tenant_id="t1", department_id="d2", classification="internal"),
        ReferenceMaterial(filename="other-owner", tenant_id="t1", owner_id="u2", classification="internal"),
        ReferenceMaterial(filename="public", tenant_id="t2", classification="public"),
    ])
    database.commit()
    with as_identity(identity()):
        assert {r.filename for r in database.query(ReferenceMaterial)} == {"one", "public"}
    with as_identity(identity(public_only=True)):
        assert {r.filename for r in database.query(ReferenceMaterial)} == {"public"}


def test_unified_redaction():
    value = {"api_key": "secret", "text": "电话13812345678 邮箱a@example.com 身份证110101199001011234"}
    result = redact(value)
    assert result["api_key"] == "[REDACTED]"
    assert "13812345678" not in result["text"] and "a@example.com" not in result["text"]
    assert model_messages([{"role": "user", "content": value["text"]}])[0]["content"] == result["text"]


def test_identity_map_and_child_tables_cannot_bypass_scope(database):
    from app.models import Draft, DraftElement, MaterialChunk
    draft = Draft(id="private", tenant_id="t2", classification="internal", title="private")
    material = ReferenceMaterial(filename="private", tenant_id="t2", classification="internal")
    database.add_all([draft, material])
    database.flush()
    database.add_all([
        DraftElement(draft_id=draft.id, name="secret", value="private"),
        MaterialChunk(material_id=material.id, chunk_index=0, text="private"),
    ])
    database.commit()
    assert database.get(Draft, draft.id) is draft
    with as_identity(identity()):
        assert governed_get(database, Draft, draft.id) is None
        assert governed_get(database, ReferenceMaterial, material.id) is None
        assert database.query(DraftElement).all() == []
        assert database.query(MaterialChunk).all() == []


def test_restricted_memory_preserves_classification_and_blocks_external_model(database):
    from dataclasses import replace
    high = replace(identity(), clearance=DataLevel.restricted)
    with as_identity(high):
        data_level_var.set(DataLevel.restricted)
        record = MemoryStore(database).put("restricted", {"text": "sensitive enterprise context"})
        database.commit()
        assert record.classification == "restricted"
    with as_identity(identity()):
        assert MemoryStore(database).read() == []
    with as_identity(high):
        assert MemoryStore(database).read()
        with pytest.raises(HTTPException) as error:
            model_messages([{"role": "user", "content": "test"}])
        assert error.value.status_code == 403
    with as_identity(identity(public_only=True)):
        assert MemoryStore(database).read() == []
        assert model_messages([{"role": "user", "content": "public"}])[0]["content"] == "public"


def test_material_bootstrap_preserves_other_owners_and_rollback_content(database):
    from app.services.materials import build_material_chunks, search_material_chunks, sync_material_document
    other = ReferenceMaterial(filename="other.txt", tenant_id="t1", department_id="d1",
                              owner_id="u2", classification="internal", text_content="other-owner evidence")
    own = ReferenceMaterial(filename="own.txt", tenant_id="t1", department_id="d1",
                            owner_id="u1", classification="internal", text_content="original evidence")
    database.add_all([other, own])
    database.commit()
    # Existing chunks predate versioned indexing.
    from app.models import MaterialChunk
    other.status = "已入库"
    database.add(MaterialChunk(material_id=other.id, chunk_index=0, text=other.text_content, embedding=[]))
    database.commit()
    with as_identity(identity()):
        build_material_chunks(database, own)
        database.commit()
        store = KnowledgeStore(database, "tenant:t1:materials")
        first = store.active()
        assert search_material_chunks(database, "original evidence")[0]["text"] == "original evidence"
        own.text_content = "updated evidence"
        build_material_chunks(database, own)
        database.commit()
        assert search_material_chunks(database, "updated evidence")[0]["text"] == "updated evidence"
        before = database.query(KnowledgeRelease).count()
        sync_material_document(database, own)
        database.commit()
        assert database.query(KnowledgeRelease).count() == before
        # A tenant-wide rollback cannot change another user's private documents.
        with pytest.raises(HTTPException):
            store.rollback(first.id)
        database.rollback()
    with as_identity(identity("u2")):
        entries = KnowledgeStore(database, "tenant:t1:materials").snapshot()["entries"]
        assert len(entries) == 1 and entries[0]["chunks"][0]["text"] == "other-owner evidence"


def test_policy_rollback_changes_actual_retrieval_and_interpretation(database):
    from app.services.policy import search_policy_clauses, interpret_clause
    from app.schemas import InterpretRequest
    with as_identity(identity()):
        create_policy_document(database, title="研发材料",
                                          content="第一条 研发补助需要提交审计报告。")
        first = KnowledgeStore(database, "public:policy").active()
        # Publish the same document with changed immutable clause content.
        store = KnowledgeStore(database, "public:policy")
        entries = store.snapshot()["entries"]
        chunks = entries[0]["chunks"]
        changed = [{**chunk, "text": chunk["text"].replace("审计报告", "税务证明")} for chunk in chunks]
        publish(store, [{**entries[0], "chunks": changed, "metadata": entries[0]["metadata_"]}])
        assert "税务证明" in search_policy_clauses(database, "研发补助")[0]["clause"].content
        store.rollback(first.id)
        database.commit()
        hits = search_policy_clauses(database, "研发补助")
        assert "审计报告" in hits[0]["clause"].content and "税务证明" not in hits[0]["clause"].content
        response = interpret_clause(database, InterpretRequest(clauseId=hits[0]["clause"].id))
        assert "审计报告" in str(response)


def test_knowledge_cancel_and_clearance_route_checks(database):
    with TestClient(app_main.app) as client:
        private = {"documents": [{"key": "a", "text": "test", "classification": "restricted"}]}
        assert client.post("/api/agent/knowledge/materials/releases", json=private, headers=headers()).status_code == 403
        public_only = {**headers(), "X-Public-Only": "true"}
        private["documents"][0]["classification"] = "internal"
        assert client.post("/api/agent/knowledge/materials/releases", json=private, headers=public_only).status_code == 403
        payload = {"public": True, "documents": [doc()], "effectiveAt": (utcnow() + timedelta(days=1)).isoformat()}
        created = client.post("/api/agent/knowledge/policy/releases", json=payload, headers=headers())
        assert created.status_code == 201, created.text
        release_id = created.json()["releaseId"]
        base = f"/api/agent/knowledge/policy/releases/{release_id}"
        assert client.post(base + "/publish?public=true", headers=headers()).status_code == 200
        assert client.post(base + "/cancel?public=true", headers=headers()).status_code == 200
        assert client.get("/api/agent/knowledge/policy/snapshot?public=true", headers=headers()).json()["entries"] == []


def test_case_incremental_noop_delete_and_unsupported_citation_fallback(database, monkeypatch):
    from app.opinion import rag
    from app.agent.platform_models import KnowledgeRelease
    monkeypatch.setattr(rag, "SessionLocal", sessionmaker(bind=database.get_bind()))
    cases = [{"id": 1, "title": "quality incident", "content": "verify product quality evidence"}]
    monkeypatch.setattr(rag.java_client, "_get", lambda _: {"cases": cases})
    first = rag.reindex_cases()
    second = rag.reindex_cases()
    assert second["knowledgeVersion"] == first["knowledgeVersion"]
    assert database.query(KnowledgeRelease).filter_by(namespace="tenant:default:opinion").count() == 1
    assert rag._retrieve("quality")[0]["knowledgeVersion"] == first["knowledgeVersion"]
    class UnsupportedLLM:
        is_mock = False
        def chat_json(self, *args, **kwargs):
            return {"content": "fabricated", "citations": [{"caseId": 1, "excerpt": "invented evidence"}]}
    monkeypatch.setattr(rag, "LLMClient", UnsupportedLLM)
    response = rag.generate_suggestion({"title": "quality"})
    assert response["model"] == "rule-based" and "fabricated" not in response["content"]
    cases.clear()
    removed = rag.reindex_cases()
    assert removed["changes"]["deleted"] == 1 and rag._retrieve("quality") == []


def test_meeting_incremental_snapshot_archive_filter_and_delete(database, monkeypatch):
    from app.meeting import pipeline, recommendation
    from app.agent.platform_models import KnowledgeRelease
    monkeypatch.setattr(pipeline, "SessionLocal", sessionmaker(bind=database.get_bind()))
    monkeypatch.setattr(recommendation, "engine", database.get_bind())
    monkeypatch.setattr(recommendation, "_active_conference_ids", lambda: {1})
    cards = [{"title": "quality", "content": "quality evidence", "sourceRef": [{"materialId": 7}]}]
    pipeline._index_cards(1, cards)
    pipeline._index_cards(2, cards)
    pipeline._index_cards(1, cards)
    assert database.query(KnowledgeRelease).filter_by(namespace="tenant:default:meeting").count() == 2
    assert [row["id"] for row in recommendation._conference_candidates(9)] == [1]
    pipeline._index_cards(1, [])
    assert recommendation._conference_candidates(9) == []


def test_download_resource_assertion_requires_trusted_identity(database):
    from app.agent.governance import authorize_download
    from dataclasses import replace
    with as_identity(replace(identity(), permissions=identity().permissions | {"opinion:read"})):
        authorize_download(database, "/static/uploads/opinion-report_7.html", "opinion-report:7")
        for path, resource in [
            ("/static/uploads/opinion-report_8.html", "opinion-report:7"),
            ("/static/uploads/opinion-report_7.md", "opinion-report:7"),
            ("/static/uploads/1_material.txt", "opinion-report:7"),
        ]:
            with pytest.raises(HTTPException):
                authorize_download(database, path, resource)
    with TestClient(app_main.app) as client:
        forged = {"X-User-Id": "u1", "X-Download-Resource": "opinion-report:7"}
        assert client.get("/static/uploads/opinion-report_7.html", headers=forged).status_code == 403
        assert client.get("/static/uploads/opinion-report_7.html", headers=headers()).status_code == 404


def test_stream_completed_failed_and_cancelled_memory(database):
    import json
    from app.agent.runtime import agent_stream, current_run
    from app.schemas import GenerateRequest
    request = GenerateRequest(eventDesc="stream input", template="test", sessionId="stream-session")
    with as_identity(identity()):
        @agent_stream("test_stream", database, request)
        def success():
            current_run.get().plan = ["planner", "retriever", "actor", "verifier"]
            yield 'data: ' + json.dumps({"type": "done", "draft": "verified result"}) + '\n\n'
        list(success())
        assert MemoryStore(database).context("stream-session")["turns"]
        before = MemoryStore(database).context("stream-session")["turns"]
        @agent_stream("test_failed", database, request)
        def failed():
            yield 'data: {"type":"error"}\n\n'
        list(failed())
        @agent_stream("test_cancelled", database, request)
        def cancelled():
            yield 'data: {"type":"delta","text":"unfinished"}\n\n'
            yield 'data: {"type":"done","draft":"should not be saved"}\n\n'
        iterator = cancelled()
        next(iterator)
        iterator.close()
        assert MemoryStore(database).context("stream-session")["turns"] == before
        assert {r.status for r in database.query(AgentRun)} == {"completed", "failed", "cancelled"}


def test_http_500_persists_failed_audit(database):
    from fastapi import FastAPI
    from app.observability import install_observability
    app = FastAPI()
    @app.get("/api/failure")
    def fail():
        raise RuntimeError("sensitive failure must not enter audit details")
    install_observability(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/api/failure", headers=headers()).status_code == 500
    row = database.query(GovernanceAudit).filter_by(resource="/api/failure").one()
    assert row.outcome == "failed" and row.details["status"] == 500
    assert "sensitive failure" not in str(row.details)


def test_run_classification_high_water_and_detail_authorization(database):
    from dataclasses import replace
    from starlette.requests import Request
    from app.agent.governance import classified_data
    from app.agent.routers import get_run, list_runs
    from app.agent.runtime import step
    request = Request({"type": "http", "headers": []})
    high = replace(identity(), clearance=DataLevel.restricted)

    @agent_run("private-task")
    def execute(db):
        with classified_data("restricted"), step("private"):
            result = {"answer": "restricted enterprise evidence"}
        with pytest.raises(HTTPException):
            model_messages([{"role": "user", "content": result["answer"]}])
        return result

    with as_identity(high):
        result = execute(database)
        row = database.get(AgentRun, result["runId"])
        assert row.classification == "restricted" and row.user_id == "u1"
        assert get_run(row.run_id, request, database)["classification"] == "restricted"
    for p in (identity(), identity("u2", tenant="t2"), identity(department="d2"),
              replace(high, public_only=True)):
        with as_identity(p):
            with pytest.raises(HTTPException) as error:
                get_run(row.run_id, request, database)
            assert error.value.status_code == 404
            assert list_runs(request, db=database) == []


def test_multimodal_external_calls_reject_nonpublic_before_reading_files(database):
    from pathlib import Path
    from app.meeting.parsers import parse_audio, parse_image
    from app.agent.governance import assert_external_model_allowed
    for level in (DataLevel.internal, DataLevel.confidential, DataLevel.restricted):
        with as_identity(identity()):
            data_level_var.set(level)
            for parse in (lambda: parse_audio(Path("missing.wav")),
                          lambda: parse_image(Path("missing.png"), "image/png")):
                with pytest.raises(HTTPException) as error:
                    parse()
                assert error.value.status_code == 403
    with as_identity(identity(public_only=True)):
        assert_external_model_allowed(binary=True)


def test_private_rag_never_overrides_public_or_cross_tenant_identity(database, monkeypatch):
    from app.opinion import rag
    from app.meeting import recommendation
    monkeypatch.setattr(rag, "SessionLocal", sessionmaker(bind=database.get_bind()))
    for p in (identity(public_only=True), identity(tenant="other")):
        with as_identity(p):
            assert rag._retrieve("secret") == []
            assert recommendation._conference_candidates(1) == []


def test_memory_purge_is_tenant_scoped_and_public_tasks_cannot_delete(database):
    from app.agent.platform_routers import audit_records
    rows = []
    for p in (identity(), identity("u2", tenant="t2")):
        with as_identity(p):
            record = MemoryStore(database).put("expired", {"text": "enterprise"})
            record.expires_at = utcnow() - timedelta(seconds=1)
            database.commit()
            rows.append(record.id)
    with as_identity(identity(public_only=True)):
        with pytest.raises(HTTPException):
            MemoryStore(database).delete(rows[0])
        with pytest.raises(HTTPException):
            MemoryStore(database).clear_session("chat")
        with pytest.raises(HTTPException):
            purge_expired(database)
        with pytest.raises(HTTPException):
            audit_records(db=database)
    with as_identity(identity()):
        assert purge_expired(database) == 1
        database.commit()
    assert database.get(MemoryRecord, rows[1]) is not None


def test_log_redaction_includes_formatted_arguments_and_tracebacks():
    import logging
    import sys
    from app.observability import TraceIdLogFilter
    try:
        raise ValueError("password=private api_key=secret a@example.com")
    except ValueError:
        record = logging.LogRecord("test", logging.ERROR, __file__, 1,
                                   "user %s", ("13812345678",), sys.exc_info())
    TraceIdLogFilter().filter(record)
    rendered = logging.Formatter("%(message)s").format(record)
    assert "13812345678" not in rendered and "a@example.com" not in rendered
    assert "password=private" not in rendered and "api_key=secret" not in rendered


def test_policy_model_consumes_memory_without_treating_it_as_evidence(database):
    calls = []
    class RecordingLLM:
        is_mock = False
        def chat_json(self, messages, **kwargs):
            calls.append(messages)
            return {"answer": "需提交审计报告。[引用1]", "usedCitations": [1]}
    with as_identity(identity()):
        create_policy_document(database, title="研发补助", content="第一条 研发补助应提交审计报告。")
        MemoryStore(database).put("style", {"style": "concise"})
        MemoryStore(database).remember_turn("chat", "上一次问研发材料", "以有效条款为准")
        database.commit()
        response = answer_policy(database, PolicyQuery(question="研发补助申请材料", sessionId="chat"),
                                 llm=RecordingLLM())
        assert response["clauses"] and len(calls) == 1
        assert "concise" in calls[0][-1]["content"] and "上一次问研发材料" in calls[0][-1]["content"]
        assert any("不是政策事实来源" in message["content"] for message in calls[0])


def test_restricted_embedding_never_calls_remote_provider(database, monkeypatch):
    from unittest.mock import Mock
    from types import SimpleNamespace
    from app.services.materials import EmbeddingClient, EmbeddingError
    monkeypatch.setattr(settings, "embedding_api_key", "test-only-key")
    client = EmbeddingClient()
    provider = Mock()
    client._client = SimpleNamespace(embeddings=provider)
    with as_identity(identity()):
        data_level_var.set(DataLevel.restricted)
        with pytest.raises(EmbeddingError):
            client.embed(["restricted text"])
    provider.create.assert_not_called()
