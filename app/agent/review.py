from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Draft
from ..observability import trace_id_var
from ..security import require_internal_token
from .models import DraftEvidence, DraftReview
from .runtime import digest


async def require_reviewer(request: Request) -> str:
    await require_internal_token(request)
    reviewer = request.headers.get("x-user-id", "").strip()
    permissions = set(request.headers.get("x-user-permissions", "").split(","))
    if not reviewer or "draft:review" not in permissions:
        raise HTTPException(403, "reviewer identity and draft:review permission required")
    return reviewer[:64]


def content_hash(draft: Draft) -> str:
    return digest({"content": draft.content, "input": draft.input_payload})


def evidence_rows(db: Session, draft_id: str) -> list[DraftEvidence]:
    return db.query(DraftEvidence).filter(DraftEvidence.draft_id == draft_id).order_by(DraftEvidence.id).all()


def evidence_fingerprint(db: Session, draft: Draft) -> str:
    return digest({
        "evidence": [{"claim": row.claim, "status": row.status, "sources": row.sources, "content_hash": row.content_hash} for row in evidence_rows(db, draft.id)],
        "fact_checks": [{"claim": row.claim, "status": row.status, "basis": row.basis} for row in draft.fact_checks],
    })


def assert_evidence_ready(db: Session, draft: Draft):
    rows = evidence_rows(db, draft.id)
    if not rows or not draft.content.strip() or not draft.fact_checks:
        raise HTTPException(422, "fact evidence is required before approval or publication")
    fingerprint = content_hash(draft)
    if any(row.status != "一致" or not row.sources or row.content_hash != fingerprint for row in rows):
        raise HTTPException(422, "unverified or stale evidence blocks approval and publication")
    if any(row.status != "一致" for row in draft.fact_checks):
        raise HTTPException(422, "fact-check risks block approval and publication")
    if {row.claim for row in rows} != {row.claim for row in draft.fact_checks}:
        raise HTTPException(422, "incomplete claim-to-evidence mapping")
    from ..services.factcheck import _mock_extract_claims
    if not set(_mock_extract_claims(draft.content)).issubset({row.claim for row in rows}):
        raise HTTPException(422, "unmapped facts in draft content")


def review_draft(db: Session, draft: Draft, reviewer: str, decision: str, comment: str):
    if draft.status != "审阅":
        raise HTTPException(422, "draft must be in review")
    if reviewer == draft.created_by:
        raise HTTPException(403, "author cannot approve their own draft")
    if not draft.created_by:
        raise HTTPException(422, "author identity is missing; re-verify with a trusted identity before review")
    if decision == "approve":
        assert_evidence_ready(db, draft)
    record = DraftReview(
        draft_id=draft.id, reviewer_id=reviewer, decision=decision, comment=comment,
        content_hash=content_hash(draft), evidence_hash=evidence_fingerprint(db, draft),
        trace_id=trace_id_var.get(),
    )
    db.add(record)
    if decision == "reject":
        draft.status = "草稿"
    db.commit()
    db.refresh(record)
    return record


def assert_publishable(db: Session, draft: Draft):
    assert_evidence_ready(db, draft)
    latest = db.query(DraftReview).filter(DraftReview.draft_id == draft.id).order_by(DraftReview.id.desc()).first()
    if not latest or latest.decision != "approve":
        raise HTTPException(422, "independent human approval is required")
    if latest.content_hash != content_hash(draft) or latest.evidence_hash != evidence_fingerprint(db, draft):
        raise HTTPException(422, "content or evidence changed; new human approval required")


def persist_evidence(db: Session, draft: Draft, report: list[dict]):
    for item in report:
        db.add(DraftEvidence(
            draft_id=draft.id, claim=item["claim"], status=item["status"],
            sources=item.get("evidence") or [], content_hash=content_hash(draft),
        ))


def review_out(record: DraftReview):
    return {
        "id": record.id, "reviewerId": record.reviewer_id, "decision": record.decision,
        "comment": record.comment, "contentHash": record.content_hash,
        "evidenceHash": record.evidence_hash, "createdAt": record.created_at,
    }
