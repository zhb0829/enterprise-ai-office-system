"""引用层线上汇总：从 `AgentRun` 与 `verification_result` 还原引用核验结果（G2）。

与 `evals.run` 的离线口径分开：这里只读取已落库的审计记录，不重新生成答案，
也不把"没有样本"当成"通过"。样本为空时所有指标为 null。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .metrics import average, percentile


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _clauses(final_answer):
    clauses = _as_dict(final_answer).get("clauses") or []
    return [item for item in clauses if isinstance(item, dict)]


def audit_row(run):
    """把一条 AgentRun 还原成可判定的引用层事实。"""
    verification = _as_dict(run.verification_result)
    final = _as_dict(run.final_answer)
    declared = [item for item in (verification.get("citation_ids") or []) if item is not None]
    clauses = _clauses(final)
    actual = [item.get("id") for item in clauses if item.get("id") is not None]
    traceable = sum(
        1 for item in clauses
        if str(item.get("excerpt") or "").strip() and str(item.get("docTitle") or "").strip()
    )
    risk_flags = [str(flag) for flag in (final.get("riskFlags") or [])]
    return {
        "run_id": run.run_id,
        "status": run.status,
        "verified": verification.get("passed"),
        "declared_ids": declared,
        "actual_ids": actual,
        "alignment": (set(declared) == set(actual)) if (declared or actual) else None,
        "has_evidence": verification.get("has_evidence"),
        "refused": verification.get("refused"),
        "degraded": bool(final.get("degraded")) or any("降级" in flag for flag in risk_flags),
        "clause_count": len(clauses),
        "traceable_count": traceable,
        "latency_ms": run.latency_ms,
    }


def summarize(rows):
    rows = list(rows)
    verified = [row["verified"] for row in rows if row["verified"] is not None]
    alignment = [row["alignment"] for row in rows if row["alignment"] is not None]
    evidence = [row["has_evidence"] for row in rows if row["has_evidence"] is not None]
    refused = [row["refused"] for row in rows if row["refused"] is not None]
    clauses = sum(row["clause_count"] for row in rows)
    traceable = sum(row["traceable_count"] for row in rows)
    latencies = [row["latency_ms"] for row in rows if row["latency_ms"]]
    return {
        "source": "agent_run.verification_result",
        "runs": len(rows),
        "verified_runs": len(verified),
        "verification_pass_rate": average([int(bool(value)) for value in verified]),
        "citation_alignment_rate": average([int(bool(value)) for value in alignment]),
        "evidence_rate": average([int(bool(value)) for value in evidence]),
        "refusal_rate": average([int(bool(value)) for value in refused]),
        "degraded_rate": average([int(bool(row["degraded"])) for row in rows]) if rows else None,
        "failed_run_rate": average([int(row["status"] != "completed") for row in rows]) if rows else None,
        "citation_traceability": (traceable / clauses) if clauses else None,
        "latency_p50_ms": round(percentile(latencies, 0.5), 2) if latencies else None,
        "latency_p95_ms": round(percentile(latencies, 0.95), 2) if latencies else None,
        "note": "线上审计口径；样本为空时指标为 null，不得解读为质量已通过",
    }


def fetch_rows(session, *, tenant="", since_days=None, limit=5000):
    from app.agent.models import AgentRun
    query = session.query(AgentRun).filter(AgentRun.intent == "policy_qa")
    if tenant:
        query = query.filter(AgentRun.tenant_id == tenant)
    if since_days:
        threshold = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=since_days)
        query = query.filter(AgentRun.started_at >= threshold)
    return query.order_by(AgentRun.started_at.desc()).limit(max(1, min(limit, 20000))).all()


def summarize_database(*, tenant="", since_days=None, limit=5000, session=None):
    """读取业务库审计并汇总；调用方自行保证有权限访问该库。"""
    if session is not None:
        rows = fetch_rows(session, tenant=tenant, since_days=since_days, limit=limit)
        return summarize(audit_row(row) for row in rows)
    from app import db as app_db
    with app_db.SessionLocal() as own_session:
        rows = fetch_rows(own_session, tenant=tenant, since_days=since_days, limit=limit)
        return summarize(audit_row(row) for row in rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="")
    parser.add_argument("--since-days", type=int, default=None)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--output", default="evals/reports/citation-online.json")
    args = parser.parse_args()
    report = {
        "generated_at": datetime.now().isoformat(),
        "tenantScope": args.tenant or "all-tenants",
        **summarize_database(tenant=args.tenant, since_days=args.since_days, limit=args.limit),
    }
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()