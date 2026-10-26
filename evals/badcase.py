"""badcase 导出（G2 线上回流第一步）。

两类来源：

1. 线上反馈：`qa_log.feedback = dislike` 或 `qa_log.resolved = False`。
2. 运行审计：`agent_run` 中失败、拒答、无引用或降级的政策问答运行。

同一 `runId` 的记录会合并标签，避免同一条问题重复出现在回流队列。
导出物含业务文本，默认按 PII/密钥规则脱敏；报告访问受控，不得进入公开文档。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import or_

from app.agent.governance import redact

MAX_TEXT = 16000
LABEL_ORDER = ("dislike", "unresolved", "run_failed", "refused", "no_citation", "degraded")


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _text(value, mask):
    text = "" if value is None else str(value)
    return redact(text)[:MAX_TEXT] if mask else text[:MAX_TEXT]


def _citation_rows(citations, mask):
    rows = []
    for item in citations or []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "clauseId": item.get("id"),
            "key": item.get("docTitle") or "",
            "docTitle": item.get("docTitle") or "",
            "articleNo": item.get("articleNo") or "",
            "excerpt": _text(item.get("excerpt"), mask),
            "sourceUrl": item.get("sourceUrl") or "",
        })
    return rows


def _case(*, source, case_id, question, answer, citations, labels, run_id="", trace_id="",
          tenant_id="", user_id="", feedback="", resolved=None, reason="", created_at=None, mask=True):
    return {
        "case_id": case_id,
        "source": source,
        "sources": [source],
        "labels": sorted(set(labels), key=LABEL_ORDER.index),
        "question": _text(question, mask),
        "answer": _text(answer, mask),
        "citations": _citation_rows(citations, mask),
        "runId": run_id,
        "traceId": trace_id,
        "tenantId": tenant_id,
        "userId": user_id,
        "feedback": feedback,
        "resolved": resolved,
        "feedbackReason": _text(reason, mask),
        "createdAt": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
    }


def _since_threshold(days):
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)


def feedback_cases(db, *, tenant="", since_days=None, limit=2000, mask=True):
    from app.models import QALog
    query = db.query(QALog).filter(or_(QALog.feedback == "dislike", QALog.resolved.is_(False)))
    if tenant:
        query = query.filter(QALog.tenant_id == tenant)
    if since_days:
        query = query.filter(QALog.created_at >= _since_threshold(since_days))
    cases = []
    for row in query.order_by(QALog.id.desc()).limit(limit).all():
        labels = []
        if row.feedback == "dislike":
            labels.append("dislike")
        if row.resolved is False:
            labels.append("unresolved")
        cases.append(_case(
            source="qa_log", case_id=f"qa-{row.id}", question=row.question, answer=row.answer,
            citations=row.citations, labels=labels, run_id=row.run_id or "",
            tenant_id=row.tenant_id or "", user_id=row.user_id or "",
            feedback=row.feedback or "", resolved=row.resolved, reason=row.feedback_reason or "",
            created_at=row.created_at, mask=mask,
        ))
    return cases


def run_cases(db, *, tenant="", since_days=None, limit=2000, mask=True):
    from app.agent.models import AgentRun
    from app.models import QALog
    query = db.query(AgentRun).filter(AgentRun.intent == "policy_qa")
    if tenant:
        query = query.filter(AgentRun.tenant_id == tenant)
    if since_days:
        query = query.filter(AgentRun.started_at >= _since_threshold(since_days))
    rows = query.order_by(AgentRun.started_at.desc()).limit(limit).all()
    # 运行审计不保存问题原文，问题文本从同一 runId 的问答流水取回。
    questions = {}
    run_ids = [row.run_id for row in rows if row.run_id]
    if run_ids:
        for qa in db.query(QALog).filter(QALog.run_id.in_(run_ids)).all():
            questions.setdefault(qa.run_id, qa.question)
    cases = []
    for row in rows:
        verification = _as_dict(row.verification_result)
        final = _as_dict(row.final_answer)
        clauses = final.get("clauses") or []
        risk_flags = [str(flag) for flag in (final.get("riskFlags") or [])]
        labels = []
        if row.status != "completed":
            labels.append("run_failed")
        if verification.get("refused"):
            labels.append("refused")
        if not clauses:
            labels.append("no_citation")
        if final.get("degraded") or any("降级" in flag for flag in risk_flags):
            labels.append("degraded")
        if not labels:
            continue
        cases.append(_case(
            source="agent_run", case_id=f"run-{row.run_id}",
            question=questions.get(row.run_id, ""), answer=final.get("answer", ""),
            citations=clauses, labels=labels, run_id=row.run_id, trace_id=row.trace_id or "",
            tenant_id=row.tenant_id or "", user_id=row.user_id or "",
            created_at=row.started_at, mask=mask,
        ))
    return cases


def merge(cases):
    """同一 runId 合并标签与来源，保留第一条的正文快照。"""
    merged, order = {}, []
    for case in cases:
        key = case.get("runId") or case["case_id"]
        if key not in merged:
            merged[key] = case
            order.append(key)
            continue
        target = merged[key]
        target["labels"] = sorted(set(target["labels"]) | set(case["labels"]), key=LABEL_ORDER.index)
        target["sources"] = sorted(set(target["sources"]) | set(case["sources"]))
        target["caseIds"] = [*target.get("caseIds", [target["case_id"]]), case["case_id"]]
        for field in ("feedback", "resolved", "feedbackReason"):
            if case.get(field):
                target[field] = case[field]
        if not target.get("runId") and case.get("runId"):
            target["runId"] = case["runId"]
    return [merged[key] for key in order]


def collect(db, *, tenant="", since_days=None, limit=2000, mask=True):
    rows = [
        *run_cases(db, tenant=tenant, since_days=since_days, limit=limit, mask=mask),
        *feedback_cases(db, tenant=tenant, since_days=since_days, limit=limit, mask=mask),
    ]
    return merge(rows)


def summarize(cases):
    counts = {label: 0 for label in LABEL_ORDER}
    for case in cases:
        for label in case["labels"]:
            counts[label] = counts.get(label, 0) + 1
    return {
        "badcases": len(cases),
        "byLabel": counts,
        "bySource": {
            source: sum(1 for case in cases if source in case["sources"])
            for source in ("qa_log", "agent_run")
        },
    }


def export_jsonl(cases, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    return {"output": str(target), "exported": len(cases)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="")
    parser.add_argument("--since-days", type=int, default=None)
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--no-mask", action="store_true", help="关闭脱敏（仅限受控环境内部排查）")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    from app import db as app_db
    with app_db.SessionLocal() as session:
        cases = collect(
            session, tenant=args.tenant, since_days=args.since_days,
            limit=args.limit, mask=not args.no_mask,
        )
    output = args.output or f"evals/reports/badcases-{datetime.now():%Y-%m-%d}.jsonl"
    result = {
        **export_jsonl(cases, output), **summarize(cases),
        "masked": not args.no_mask, "tenantScope": args.tenant or "all-tenants",
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()