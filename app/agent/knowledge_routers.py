from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..security import require_internal_token
from .governance import DataLevel, audit, principal_var, utc_naive
from .knowledge import KnowledgeStore, namespace_for, search_knowledge
from .platform_models import KnowledgeRelease

router = APIRouter(dependencies=[Depends(require_internal_token)])


class KnowledgeDocument(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=200000)
    metadata: dict = Field(default_factory=dict)
    classification: str = "internal"
    department_id: str = Field(default="", max_length=64)
    effective_at: datetime | None = None
    expires_at: datetime | None = None


class ReleaseInput(BaseModel):
    documents: list[KnowledgeDocument] = Field(default_factory=list, max_length=100)
    deletedKeys: list[str] = Field(default_factory=list, max_length=100)
    public: bool = False
    effectiveAt: datetime | None = None
    expiresAt: datetime | None = None
    expectedGeneration: int = Field(default=0, ge=0)


def store_for(db, domain, public):
    p = principal_var.get()
    p.require("knowledge:read")
    if p.public_only and not public:
        raise HTTPException(403, "public-only tasks require a public knowledge namespace")
    return KnowledgeStore(db, namespace_for(domain, public=public))


@router.post("/knowledge/{domain}/releases", status_code=201)
def stage_release(domain: str, payload: ReleaseInput, db: Session = Depends(get_db)):
    p = principal_var.get()
    p.require("knowledge:write")
    if payload.public:
        p.require("knowledge:publish")
    documents = []
    for item in payload.documents:
        if item.classification not in DataLevel.__members__:
            raise HTTPException(422, "invalid data classification")
        if DataLevel[item.classification] > p.clearance:
            raise HTTPException(403, "classification exceeds trusted clearance")
        if p.public_only and item.classification != "public":
            raise HTTPException(403, "public-only task cannot publish private knowledge")
        if item.department_id and item.department_id != p.department_id:
            raise HTTPException(403, "department boundary mismatch")
        documents.append({
            **item.model_dump(), "tenant_id": "" if payload.public else p.tenant_id,
            "owner_id": "",
        })
    try:
        row = store_for(db, domain, payload.public).stage(
            documents, deleted_keys=payload.deletedKeys, effective_at=payload.effectiveAt,
            expires_at=payload.expiresAt, expected_generation=payload.expectedGeneration,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "concurrent knowledge staging") from exc
    return {"releaseId": row.id, "version": row.version, "changes": row.changes}


@router.post("/knowledge/{domain}/releases/{release_id}/publish")
def publish_release(domain: str, release_id: str, public: bool = False, db: Session = Depends(get_db)):
    principal_var.get().require("knowledge:publish")
    row = store_for(db, domain, public).publish(release_id)
    db.commit()
    return {"releaseId": row.id, "version": row.version, "status": row.status}


@router.post("/knowledge/{domain}/releases/{release_id}/cancel")
def cancel_release(domain: str, release_id: str, public: bool = False, db: Session = Depends(get_db)):
    principal_var.get().require("knowledge:publish")
    store = store_for(db, domain, public)
    row = db.get(KnowledgeRelease, release_id)
    from .governance import utcnow
    if not row or row.namespace != store.namespace:
        raise HTTPException(404, "release not found")
    if row.status != "staged" and not (row.status == "published" and row.effective_at > utcnow()):
        raise HTTPException(409, "only staged or future releases can be cancelled")
    from .platform_models import KnowledgeHead
    from sqlalchemy import update
    generation = db.get(KnowledgeHead, store.namespace, populate_existing=True).generation
    changed = db.execute(update(KnowledgeHead).where(
        KnowledgeHead.namespace == store.namespace, KnowledgeHead.generation == generation,
    ).values(generation=generation + 1))
    if changed.rowcount != 1:
        raise HTTPException(409, "concurrent release cancellation")
    row.status = "cancelled"
    audit(db, "knowledge.cancel", store.namespace, details={"releaseId": row.id})
    db.commit()
    return {"releaseId": row.id, "status": row.status}


@router.post("/knowledge/{domain}/releases/{release_id}/rollback")
def rollback_release(domain: str, release_id: str, public: bool = False, db: Session = Depends(get_db)):
    principal_var.get().require("knowledge:publish")
    row = store_for(db, domain, public).rollback(release_id)
    db.commit()
    return {"releaseId": row.id, "version": row.version, "status": row.status}


@router.get("/knowledge/{domain}/releases")
def releases(domain: str, public: bool = False, db: Session = Depends(get_db)):
    store = store_for(db, domain, public)
    return jsonable_encoder([{
        "releaseId": r.id, "version": r.version, "status": r.status, "effectiveAt": r.effective_at,
        "expiresAt": r.expires_at, "changes": r.changes, "manifestHash": r.manifest_hash,
    } for r in db.query(KnowledgeRelease).filter_by(namespace=store.namespace).order_by(KnowledgeRelease.version.desc()).limit(100)])


@router.get("/knowledge/{domain}/snapshot")
def snapshot(domain: str, public: bool = False, asOf: datetime | None = None, db: Session = Depends(get_db)):
    store = store_for(db, domain, public)
    result = store.snapshot(utc_naive(asOf))
    audit(db, "knowledge.read", store.namespace, details={"releaseId": result["releaseId"], "entries": len(result["entries"])})
    db.commit()
    return jsonable_encoder(result)


@router.get("/knowledge/{domain}/search")
def search(domain: str, q: str, public: bool = False, limit: int = 6, db: Session = Depends(get_db)):
    store_for(db, domain, public)
    result = search_knowledge(db, domain, q, public=public, limit=limit)
    db.commit()
    return jsonable_encoder(result)
