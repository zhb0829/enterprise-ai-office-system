from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..security import require_internal_token
from .governance import principal_var, utcnow
from .memory import MemoryStore, purge_expired
from .platform_models import GovernanceAudit

router = APIRouter(dependencies=[Depends(require_internal_token)])


class MemoryWrite(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: dict
    kind: str = "long"
    scope: str = "user"
    sessionId: str = Field(default="", max_length=128)
    ttlSeconds: int = Field(default=2592000, ge=1, le=31536000)
    expectedRevision: int = Field(default=0, ge=0)


@router.get("/memory")
def memories(sessionId: str = "", scope: str = "user", db: Session = Depends(get_db)):
    rows = MemoryStore(db).read(sessionId, scope)
    result = [{"id": r.id, "key": r.key, "kind": r.kind, "value": r.value, "revision": r.revision,
               "scope": r.scope, "sessionId": r.session_id, "expiresAt": r.expires_at} for r in rows]
    db.commit()
    return jsonable_encoder(result)


@router.put("/memory")
def put_memory(payload: MemoryWrite, db: Session = Depends(get_db)):
    try:
        row = MemoryStore(db).put(
            payload.key, payload.value, kind=payload.kind, scope=payload.scope, session_id=payload.sessionId,
            ttl_seconds=payload.ttlSeconds, expected_revision=payload.expectedRevision,
        )
        db.commit()
        return {"id": row.id, "revision": row.revision}
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "concurrent memory update") from exc


@router.delete("/memory/session/{session_id}")
def clear_session(session_id: str, db: Session = Depends(get_db)):
    count = MemoryStore(db).clear_session(session_id)
    db.commit()
    return {"deleted": count}


@router.delete("/memory/{record_id}")
def delete_memory(record_id: str, db: Session = Depends(get_db)):
    MemoryStore(db).delete(record_id)
    db.commit()
    return {"deleted": True}


@router.post("/memory/purge")
def purge_memory(db: Session = Depends(get_db)):
    principal_var.get().require("agent:admin")
    count = purge_expired(db)
    db.commit()
    return {"deleted": count}


@router.get("/governance/audit")
def audit_records(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    p = principal_var.get()
    p.require("agent:audit")
    if p.public_only:
        raise HTTPException(403, "public-only tasks cannot inspect enterprise audit records")
    rows = db.query(GovernanceAudit).filter(
        GovernanceAudit.tenant_id == p.tenant_id, GovernanceAudit.expires_at > utcnow(),
        or_(GovernanceAudit.department_id == "", GovernanceAudit.department_id == p.department_id),
    ).order_by(GovernanceAudit.id.desc()).limit(limit).all()
    return jsonable_encoder([{
        "id": r.id, "userId": r.user_id, "departmentId": r.department_id, "traceId": r.trace_id,
        "action": r.action, "resource": r.resource, "outcome": r.outcome, "details": r.details,
        "createdAt": r.created_at,
    } for r in rows])
