"""G2 评测四层口径与线上回流闭环的回归测试。"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import main as app_main
from app.agent.models import AgentRun
from app.models import QALog
from tests.conftest import trusted_headers


@pytest.fixture(autouse=True)
def use_offline_embeddings(monkeypatch):
    from app.services import materials
    monkeypatch.setattr(materials.settings, "embedding_api_key", "")


@pytest.fixture()
def sqlite_env(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app_db.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(app_db, "engine", engine)
    monkeypatch.setattr(app_db, "SessionLocal", session_factory)
    monkeypatch.setattr(app_main, "engine", engine)
    monkeypatch.setattr(app_main, "SessionLocal", session_factory)
    monkeypatch.setattr(app_main, "load_seed_templates", lambda db: 0)
    return session_factory


# ===== 四层报告 =====

def test_offline_report_has_four_layers_and_keeps_legacy_summary():
    from evals.run import evaluate
    report = evaluate("offline")
    assert report["synthetic"] is True
    assert report["dataset_source"] == "synthetic"
    layers = report["layers"]
    assert set(layers) == {"retrieval", "generation", "citation", "experience"}
    # 检索层沿用原口径，摘要字段保持向后兼容
    assert layers["retrieval"]["recall_at_k"] == report["summary"]["recall_at_k"]
    assert report["summary"]["total"] == report["summary"]["passed"] == 38
    # 离线生成层必须自曝口径，不得冒充真实质量
    assert layers["generation"]["source"] == "lexical-fallback"
    assert layers["generation"]["application"] == "engineering-regression-only"
    assert layers["generation"]["answer_accuracy"] is not None
    # 引用层与体验层样本来自政策问答
    assert layers["citation"]["citation_traceability"] is not None
    assert layers["citation"]["refusal_rate"] is not None
    assert layers["experience"]["latency_samples"] > 0
    assert layers["experience"]["latency_p95_ms"] >= layers["experience"]["latency_p50_ms"]


def test_reflow_dataset_is_required_and_never_substituted(tmp_path, monkeypatch):
    import evals.run as run_module
    monkeypatch.setattr(run_module, "REFLOW_DIR", tmp_path / "empty")
    with pytest.raises(FileNotFoundError):
        run_module.load_reflow()


# ===== 引用层线上汇总（AgentRun + verification_result）=====

def _run(run_id, *, passed=None, citation_ids=None, has_evidence=None, refused=None,
         clauses=None, risk_flags=None, status="completed", latency=10, degraded=None):
    final = {"clauses": clauses or [], "riskFlags": risk_flags or []}
    if degraded is not None:
        final["degraded"] = degraded
    return SimpleNamespace(
        run_id=run_id, status=status, latency_ms=latency,
        verification_result={
            "passed": passed, "citation_ids": citation_ids or [],
            "has_evidence": has_evidence, "refused": refused,
        },
        final_answer=final,
    )


def test_citation_audit_summarizes_verification_results():
    from evals.citation_audit import audit_row, summarize
    rows = [
        _run("r1", passed=True, citation_ids=[1, 2], has_evidence=True, refused=False,
             clauses=[{"id": 1, "docTitle": "A", "excerpt": "x"}, {"id": 2, "docTitle": "A", "excerpt": "y"}]),
        _run("r2", passed=True, citation_ids=[], has_evidence=False, refused=True),
        _run("r3", passed=False, citation_ids=[3], has_evidence=False, refused=False,
             clauses=[{"id": 4, "docTitle": "B", "excerpt": "z"}],
             risk_flags=["模型未返回可验证引用，已降级为检索结果。"]),
    ]
    summary = summarize(audit_row(row) for row in rows)
    assert summary["runs"] == 3
    assert summary["verification_pass_rate"] == pytest.approx(2 / 3)
    # 只有能对齐的样本参与对齐率：一条一致、一条不一致
    assert summary["citation_alignment_rate"] == pytest.approx(0.5)
    assert summary["refusal_rate"] == pytest.approx(1 / 3)
    assert summary["degraded_rate"] == pytest.approx(1 / 3)
    assert summary["citation_traceability"] == pytest.approx(1.0)
    assert summary["latency_p50_ms"] == 10


def test_citation_audit_reports_null_without_samples():
    from evals.citation_audit import summarize
    summary = summarize([])
    assert summary["runs"] == 0
    assert summary["verification_pass_rate"] is None
    assert summary["citation_traceability"] is None
    assert summary["latency_p95_ms"] is None


# ===== 线上反馈落库 =====

def test_policy_feedback_updates_qa_log(sqlite_env):
    with TestClient(app_main.app, headers=trusted_headers("policy:read")) as client:
        chat = client.post("/api/policy/chat", json={"question": "不存在的法规条款是什么？"})
        assert chat.status_code == 200
        with sqlite_env() as db:
            row = db.query(QALog).order_by(QALog.id.desc()).first()
            assert row is not None and row.tenant_id == "default" and row.user_id == "test-user"
            assert row.run_id and row.feedback == "" and row.resolved is None
            qa_log_id = row.id
        response = client.post("/api/policy/feedback", json={
            "qaLogId": qa_log_id, "rating": "dislike", "resolved": False, "reason": "没有回答我的问题",
        })
    assert response.status_code == 200
    assert response.json()["rating"] == "dislike"
    with sqlite_env() as db:
        row = db.get(QALog, qa_log_id)
        assert row.feedback == "dislike"
        assert row.resolved is False
        assert row.feedback_reason == "没有回答我的问题"
        assert row.feedback_user_id == "test-user"
        assert row.feedback_at is not None


def test_policy_feedback_rejects_other_tenant_and_other_user(sqlite_env):
    with sqlite_env() as db:
        db.add(QALog(
            session_id="", tenant_id="default", user_id="someone-else", run_id="",
            question="问题", answer="答案", citations=[], model="offline", latency_ms=1,
        ))
        db.commit()
        qa_log_id = db.query(QALog).order_by(QALog.id.desc()).first().id

    other_tenant = {
        "X-Internal-Token": trusted_headers("policy:read")["X-Internal-Token"],
        "X-User-Id": "test-user", "X-Tenant-Id": "other-tenant", "X-User-Permissions": "policy:read",
    }
    with TestClient(app_main.app, headers=other_tenant) as client:
        cross_tenant = client.post("/api/policy/feedback", json={"qaLogId": qa_log_id, "rating": "like"})
    assert cross_tenant.status_code == 404

    with TestClient(app_main.app, headers=trusted_headers("policy:read")) as client:
        other_user = client.post("/api/policy/feedback", json={"qaLogId": qa_log_id, "rating": "like"})
    assert other_user.status_code == 403


# ===== badcase 导出 =====

def test_badcase_export_merges_labels_and_masks_pii(sqlite_env, tmp_path):
    from evals.badcase import collect, export_jsonl, summarize
    with sqlite_env() as db:
        db.add(QALog(
            session_id="", tenant_id="default", user_id="u1", run_id="run-1",
            question="联系人手机号13800138000的补贴标准是什么？", answer="未检索到相关规定",
            citations=[], model="offline", latency_ms=5, feedback="dislike", resolved=False,
            feedback_reason="答非所问",
        ))
        db.add(AgentRun(
            run_id="run-1", trace_id="t1", user_id="u1", session_id="", tenant_id="default",
            department_id="", intent="policy_qa", status="failed", plan=[], steps=[],
            verification_result={"passed": False, "citation_ids": [], "has_evidence": False, "refused": True},
            final_answer={"clauses": [], "riskFlags": [], "degraded": True},
            usage={}, latency_ms=12, error="RuntimeError",
            started_at=datetime(2026, 10, 20, 10, 0, 0), finished_at=None,
        ))
        db.commit()
        cases = collect(db)
    assert len(cases) == 1  # 同一 runId 合并为一条 badcase
    case = cases[0]
    assert set(case["labels"]) == {"dislike", "unresolved", "run_failed", "refused", "no_citation", "degraded"}
    assert case["sources"] == ["agent_run", "qa_log"]
    assert "13800138000" not in case["question"]
    assert "[PHONE_REDACTED]" in case["question"]
    assert summarize(cases)["byLabel"]["dislike"] == 1
    output = tmp_path / "badcases.jsonl"
    assert export_jsonl(cases, output)["exported"] == 1
    stored = json.loads(output.read_text(encoding="utf-8").strip())
    assert stored["runId"] == "run-1" and stored["labels"]


def test_badcase_keeps_clean_runs_out(sqlite_env):
    from evals.badcase import collect
    with sqlite_env() as db:
        db.add(AgentRun(
            run_id="ok-1", trace_id="t", user_id="u1", session_id="", tenant_id="default",
            department_id="", intent="policy_qa", status="completed", plan=[], steps=[],
            verification_result={"passed": True, "citation_ids": [1], "has_evidence": True, "refused": False},
            final_answer={"clauses": [{"id": 1, "docTitle": "A", "excerpt": "x"}], "riskFlags": [], "degraded": False},
            usage={}, latency_ms=9, error="",
            started_at=datetime(2026, 10, 20, 10, 0, 0), finished_at=None,
        ))
        db.commit()
        assert collect(db) == []


# ===== 回流测试集 =====

def _badcase_row():
    return {
        "case_id": "qa-1", "labels": ["dislike"], "question": "研发补助的申报材料有哪些？",
        "answer": "未检索到相关规定", "runId": "run-1",
        "citations": [{
            "clauseId": 3, "key": "研发补助管理办法", "docTitle": "研发补助管理办法",
            "articleNo": "第十一条", "excerpt": "第十一条 申请研发补助应当提交研发项目立项证明、费用明细与验收报告。",
            "sourceUrl": "https://example.com/policy",
        }],
    }


def test_reflow_draft_validate_promote(tmp_path):
    from evals.reflow import draft, promote, validate, write_dataset
    pending = draft([_badcase_row()], "2026-10-25")
    assert pending["state"] == "pending-labeling"
    assert pending["synthetic"] is False
    assert pending["corpus"] and pending["corpus"][0]["key"] == "研发补助管理办法"
    assert pending["cases"][0]["labeled"] is False
    assert pending["cases"][0]["candidateClauses"][0]["articleNo"] == "第十一条"

    errors = validate(pending)
    assert any("未标注" in error for error in errors)

    case = pending["cases"][0]
    case.update(labeled=True, labeledBy="张三", labeledAt="2026-10-25")
    case["expected"] = [["研发补助管理办法", "第十一条"]]
    pending["labeled_by"], pending["labeled_at"] = "张三", "2026-10-25"
    assert validate(pending) == []

    real = promote(pending)
    assert real["synthetic"] is False
    assert real["dataset_version"] == "production-reflow-2026-10-25"
    assert real["cases"][0]["refusal"] is False
    path = write_dataset(real, tmp_path / "real-2026-10-25.json")
    assert json.loads((tmp_path / "real-2026-10-25.json").read_text(encoding="utf-8"))["labeled_by"] == "张三"
    assert path.endswith("real-2026-10-25.json")


def test_reflow_promote_refuses_unlabeled_and_unknown_clause():
    from evals.reflow import draft, promote, validate
    pending = draft([_badcase_row()], "2026-10-25")
    case = pending["cases"][0]
    case.update(labeled=True, labeledBy="张三", labeledAt="2026-10-25")
    case["expected"] = [["不存在的文档", "第一条"]]
    pending["labeled_by"], pending["labeled_at"] = "张三", "2026-10-25"
    errors = validate(pending)
    assert any("语料 key 不存在" in error for error in errors)
    with pytest.raises(ValueError):
        promote(pending)


def test_reflow_reads_labeling_files_with_bom(tmp_path):
    """人工标注常用 Windows 工具保存（带 BOM），读取必须兼容。"""
    from evals.reflow import draft, load_json, write_dataset
    pending = draft([_badcase_row()], "2026-10-25")
    path = tmp_path / "pending-bom.json"
    path.write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8-sig")
    assert load_json(path)["cases"][0]["question"].startswith("研发补助")
    assert write_dataset(pending, tmp_path / "plain.json").endswith("plain.json")


# ===== 劣化门禁 =====

def _report(recall=1.0, fallback=1.0, version="synthetic-p0-v1", total=38, pass_rate=1, digest="d" * 64):
    return {
        "dataset_version": version, "dataset_source": "synthetic", "dataset_digest": digest,
        "synthetic": True, "mode": "offline",
        "summary": {"total": total, "passed": total, "pass_rate": pass_rate},
        "layers": {
            "retrieval": {"recall_at_k": recall, "mrr": 0.9, "ndcg_at_k": 0.9},
            "generation": {"answer_accuracy": 1.0, "answer_completeness": 1.0},
            "citation": {"citation_precision": 1.0, "citation_traceability": 1.0, "refusal_rate": 0.25},
            "experience": {"fallback_rate": fallback, "latency_p50_ms": 7.0, "latency_p95_ms": 9.0},
        },
    }


def test_gate_passes_on_identical_report():
    from evals.gate import compare
    result = compare(_report(), _report())
    assert result["passed"] is True
    assert result["failures"] == []


def test_gate_blocks_retrieval_and_fallback_regression():
    from evals.gate import compare
    result = compare(_report(recall=0.9, fallback=1.0), _report(recall=1.0, fallback=0.5))
    assert result["passed"] is False
    regressed = {(row["layer"], row["metric"]) for row in result["failures"] if row.get("status") == "regressed"}
    assert ("retrieval", "recall_at_k") in regressed
    assert ("experience", "fallback_rate") in regressed


def test_gate_blocks_dataset_change_and_imperfect_pass_rate():
    from evals.gate import compare
    result = compare(_report(version="production-reflow-2026-10-25", total=20, pass_rate=0.9), _report())
    checks = {failure["check"] for failure in result["failures"] if "check" in failure}
    assert {"dataset_version", "cases", "pass_rate"} <= checks


def test_gate_requires_baseline_file(tmp_path, monkeypatch):
    import evals.gate as gate
    report_path = tmp_path / "ci.json"
    report_path.write_text(json.dumps(_report(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "evals.gate", "--report", str(report_path), "--baseline", str(tmp_path / "missing.json"),
    ])
    with pytest.raises(SystemExit):
        gate.main()


def test_gate_update_baseline_writes_file(tmp_path, monkeypatch):
    import evals.gate as gate
    report_path = tmp_path / "ci.json"
    baseline_path = tmp_path / "baseline.json"
    report_path.write_text(json.dumps(_report(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "evals.gate", "--report", str(report_path), "--baseline", str(baseline_path), "--update-baseline",
    ])
    gate.main()
    stored = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert stored["dataset_version"] == "synthetic-p0-v1"
    assert stored["layers"]["retrieval"]["recall_at_k"] == 1.0


# ===== 复审后加固：摘要、缺失指标与基线保护 =====

def test_gate_blocks_equal_size_case_swap_via_digest():
    """等量替换用例不改变数量，但摘要会变，必须阻断。"""
    from evals.gate import compare
    result = compare(_report(digest="a" * 64), _report(digest="b" * 64))
    assert result["passed"] is False
    assert {"dataset_digest"} <= {failure["check"] for failure in result["failures"] if "check" in failure}


def test_gate_treats_disappearing_metric_as_regression():
    """清空标注让指标变 NULL，不能因此静默放行。"""
    from evals.gate import compare
    current = _report()
    current["layers"]["generation"]["answer_accuracy"] = None
    result = compare(current, _report())
    assert result["passed"] is False
    regressed = [row for row in result["comparisons"] if row["metric"] == "answer_accuracy"][0]
    assert regressed["status"] == "regressed"
    assert "NULL" in regressed["reason"]


def test_gate_update_baseline_refuses_silent_downgrade(tmp_path):
    import evals.gate as gate
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(_report(), ensure_ascii=False), encoding="utf-8")

    with pytest.raises(SystemExit):
        gate.update_baseline(_report(recall=0.8), baseline_path)
    # 原基线未被改写
    assert json.loads(baseline_path.read_text(encoding="utf-8"))["layers"]["retrieval"]["recall_at_k"] == 1.0

    path, problems = gate.update_baseline(
        _report(recall=0.8), baseline_path, force=True, approver="张三", reason="切片策略 v3 变更",
    )
    stored = gate.load_json(path)
    assert stored["layers"]["retrieval"]["recall_at_k"] == 0.8
    assert "张三" in stored["note"] and "切片策略 v3 变更" in stored["note"]
    assert problems and any("recall_at_k" in item for item in problems)


def test_gate_update_baseline_refuses_imperfect_pass_rate(tmp_path):
    import evals.gate as gate
    baseline_path = tmp_path / "baseline.json"
    with pytest.raises(SystemExit):
        gate.update_baseline(_report(pass_rate=0.9), baseline_path)
    assert not baseline_path.exists()


# ===== 复审后加固：回流集评测路径强制校验 =====

def _labeled_reflow_payload():
    from evals.reflow import draft, promote
    pending = draft([_badcase_row()], "2026-10-25")
    case = pending["cases"][0]
    case.update(labeled=True, labeledBy="张三", labeledAt="2026-10-25")
    case["expected"] = [["研发补助管理办法", "第十一条"]]
    pending["labeled_by"], pending["labeled_at"] = "张三", "2026-10-25"
    return promote(pending)


def test_reflow_evaluation_rejects_unlabeled_dataset(tmp_path, monkeypatch):
    import evals.run as run_module
    payload = _labeled_reflow_payload()
    payload["cases"][0]["labeled"] = False
    (tmp_path / "real-2026-10-25.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8",
    )
    monkeypatch.setattr(run_module, "REFLOW_DIR", tmp_path)
    with pytest.raises(RuntimeError) as error:
        run_module.load_reflow()
    assert "拒绝评测" in str(error.value)
    assert "未标注" in str(error.value)


def test_reflow_evaluation_rejects_synthetic_copy(tmp_path, monkeypatch):
    """把合成集抄成 real-*.json 也必须被拒绝，不能冒充真实语料验收。"""
    import evals.run as run_module
    payload = _labeled_reflow_payload()
    payload["synthetic"] = True
    payload["state"] = "pending-labeling"
    (tmp_path / "real-2026-10-25.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8",
    )
    monkeypatch.setattr(run_module, "REFLOW_DIR", tmp_path)
    with pytest.raises(RuntimeError) as error:
        run_module.load_reflow()
    message = str(error.value)
    assert "synthetic 必须为 false" in message
    assert "state 必须为 labeled" in message


def test_reflow_evaluation_end_to_end(tmp_path, monkeypatch):
    import evals.run as run_module
    payload = _labeled_reflow_payload()
    payload["cases"][0]["asOf"] = "2026-10-11"
    # 地区过滤要与语料元数据一致，否则检索必然为空
    payload["cases"][0]["region"] = "全国"
    payload["corpus"][0]["region"] = "全国"
    (tmp_path / "real-2026-10-25.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8",
    )
    monkeypatch.setattr(run_module, "REFLOW_DIR", tmp_path)
    report = run_module.evaluate("offline", "reflow")
    assert report["dataset_source"] == "production-reflow"
    assert report["synthetic"] is False
    assert report["dataset_validation"]["passed"] is True
    assert report["dataset_validation"]["checked_by"] == "evals.reflow.validate"
    assert len(report["dataset_digest"]) == 64
    assert report["summary"]["total"] == 1
    assert report["summary"]["pass_rate"] == 1
    assert report["labels"]["labeled_by"] == ["张三"]
    # 标注了 expected 但没标 answerContains → 生成层缺样本记 null，不补零
    assert report["layers"]["generation"]["answer_accuracy"] is None
    assert report["layers"]["generation"]["samples"]["answer_accuracy"] == 0
    assert report["layers"]["retrieval"]["samples"]["recall_at_k"] == 1
    assert report["layers"]["citation"]["application"] == "structural-regression-only"


def test_reflow_validate_rejects_unreproducible_clause():
    """expected 写的条款若在语料里切不出来，必须在晋级前拒绝。"""
    from evals.reflow import draft, validate
    pending = draft([_badcase_row()], "2026-10-25")
    case = pending["cases"][0]
    case.update(labeled=True, labeledBy="张三", labeledAt="2026-10-25")
    case["expected"] = [["研发补助管理办法", "第九十九条"]]
    pending["labeled_by"], pending["labeled_at"] = "张三", "2026-10-25"
    errors = validate(pending)
    assert any("切分后不存在" in error for error in errors)


def test_reflow_promote_keeps_retrieval_context():
    from evals.reflow import promote
    payload = _labeled_reflow_payload()
    payload["cases"][0].update(asOf="2026-10-11", region="全国", policyName="研发补助管理办法")
    case = promote(payload)["cases"][0]
    assert case["asOf"] == "2026-10-11"
    assert case["region"] == "全国"
    assert case["policyName"] == "研发补助管理办法"
    assert "industry" not in case  # 未填写的上下文不写入，避免空值污染评测


# ===== 复审后加固：反馈权限与审计 =====

def test_policy_feedback_requires_audit_for_ownerless_record(sqlite_env):
    with sqlite_env() as db:
        db.add(QALog(
            session_id="", tenant_id="default", user_id="", run_id="",
            question="后台写入的问题", answer="答案", citations=[], model="offline", latency_ms=1,
        ))
        db.commit()
        qa_log_id = db.query(QALog).order_by(QALog.id.desc()).first().id

    with TestClient(app_main.app, headers=trusted_headers("policy:read")) as client:
        denied = client.post("/api/policy/feedback", json={"qaLogId": qa_log_id, "rating": "dislike"})
    assert denied.status_code == 403

    with TestClient(app_main.app, headers=trusted_headers("policy:read,agent:audit")) as client:
        allowed = client.post("/api/policy/feedback", json={"qaLogId": qa_log_id, "rating": "dislike"})
    assert allowed.status_code == 200
    with sqlite_env() as db:
        assert db.get(QALog, qa_log_id).feedback == "dislike"


def test_policy_feedback_writes_governance_audit(sqlite_env):
    from app.agent.platform_models import GovernanceAudit
    with TestClient(app_main.app, headers=trusted_headers("policy:read")) as client:
        assert client.post("/api/policy/chat", json={"question": "不存在的法规条款是什么？"}).status_code == 200
        with sqlite_env() as db:
            qa_log_id = db.query(QALog).order_by(QALog.id.desc()).first().id
        assert client.post(
            "/api/policy/feedback",
            json={"qaLogId": qa_log_id, "rating": "dislike", "resolved": False, "reason": "答非所问"},
        ).status_code == 200
    with sqlite_env() as db:
        rows = db.query(GovernanceAudit).filter(GovernanceAudit.action == "policy.feedback").all()
        assert rows and rows[-1].outcome == "allowed"
        assert rows[-1].resource == f"qa_log:{qa_log_id}"
        assert rows[-1].details["rating"] == "dislike"