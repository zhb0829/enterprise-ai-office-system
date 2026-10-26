from __future__ import annotations

import uuid
import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from .governance import DataLevel, Principal, audit, data_level_var, principal_var, redact, utcnow
from .platform_models import MemoryRecord


class MemoryStore:
    def __init__(self, db: Session, principal: Principal | None = None):
        self.db = db
        self.p = principal or principal_var.get()

    def _scope(self, scope):
        self.p.require("memory:read")
        if scope not in {"user", "department", "tenant"}:
            raise HTTPException(422, "invalid memory scope")
        if scope == "department" and not self.p.department_id:
            raise HTTPException(422, "department identity required")
        return {
            "tenant_id": self.p.tenant_id,
            "department_id": self.p.department_id if scope in {"user", "department"} else "",
            "user_id": self.p.user_id if scope == "user" else "",
            "scope": scope,
        }

    def _query(self, scope="user"):
        return self.db.query(MemoryRecord).filter_by(**self._scope(scope))

    def put(self, key, value, *, kind="long", session_id="", scope="user", ttl_seconds=2592000, expected_revision=0):
        self.p.require("memory:write" if scope == "user" else f"memory:{scope}:write")
        if kind not in {"short", "long", "summary"} or not 1 <= ttl_seconds <= 31536000:
            raise HTTPException(422, "invalid memory kind or retention")
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 32768:
            raise HTTPException(422, "memory value exceeds 32 KiB")
        if self.p.public_only:
            raise HTTPException(403, "public-only tasks cannot write private memory")
        if kind != "long" and (not session_id or scope != "user"):
            raise HTTPException(422, "session memory requires a user-scoped session")
        if kind == "long":
            session_id = ""
        query = self._query(scope).filter_by(key=key, kind=kind, session_id=session_id)
        row = query.first()
        classification = max(DataLevel.internal, data_level_var.get(),
                             DataLevel[row.classification] if row else DataLevel.public)
        if classification > self.p.clearance:
            raise HTTPException(403, "memory classification exceeds trusted clearance")
        now = utcnow()
        values = dict(value=redact(value), classification=classification.name,
                      updated_at=now, expires_at=now + timedelta(seconds=ttl_seconds))
        if row:
            if row.revision != expected_revision:
                raise HTTPException(409, {"message": "memory revision conflict", "revision": row.revision})
            result = self.db.execute(update(MemoryRecord).where(
                MemoryRecord.id == row.id, MemoryRecord.revision == expected_revision,
            ).values(**values, revision=expected_revision + 1))
            if result.rowcount != 1:
                raise HTTPException(409, "memory revision conflict")
            self.db.expire(row)
        else:
            if expected_revision != 0:
                raise HTTPException(409, "memory has been deleted")
            row = MemoryRecord(id=uuid.uuid4().hex, **self._scope(scope), key=key, kind=kind,
                               session_id=session_id, revision=1, **values)
            self.db.add(row)
        audit(self.db, "memory.put", key, details={"scope": scope, "kind": kind}, principal=self.p)
        self.db.flush()
        return row

    def read(self, session_id="", scope="user"):
        query = self._query(scope).filter(MemoryRecord.expires_at > utcnow())
        query = query.filter(or_(MemoryRecord.kind == "long", MemoryRecord.session_id == session_id))
        rows = query.order_by(MemoryRecord.updated_at).all()
        # Public tasks must not consume private preferences or previous enterprise conversations.
        rows = [row for row in rows if self.p.can_read(
            row.classification, row.tenant_id, row.department_id, row.user_id,
        )]
        for row in rows:
            data_level_var.set(max(data_level_var.get(), DataLevel[row.classification]))
        audit(self.db, "memory.read", session_id or scope, details={"count": len(rows)}, principal=self.p)
        return rows

    def delete(self, record_id):
        self.p.require("memory:write")
        if self.p.public_only:
            raise HTTPException(403, "public-only tasks cannot delete enterprise memory")
        row = self.db.get(MemoryRecord, record_id)
        if not row or not self.p.can_read(row.classification, row.tenant_id, row.department_id, row.user_id):
            raise HTTPException(404, "memory not found")
        query = self._query(row.scope).filter_by(id=record_id)
        if row.scope != "user":
            self.p.require(f"memory:{row.scope}:write")
        if not query.first():
            raise HTTPException(404, "memory not found")
        query.delete(synchronize_session=False)
        audit(self.db, "memory.delete", record_id, principal=self.p)

    def clear_session(self, session_id):
        self.p.require("memory:write")
        if self.p.public_only:
            raise HTTPException(403, "public-only tasks cannot delete enterprise memory")
        count = self._query().filter(
            MemoryRecord.session_id == session_id, MemoryRecord.kind.in_(["short", "summary"]),
            MemoryRecord.classification.in_([level.name for level in DataLevel if level <= self.p.clearance]),
        ).delete(synchronize_session=False)
        audit(self.db, "memory.clear_session", session_id, details={"count": count}, principal=self.p)
        return count

    def remember_turn(self, session_id, question, answer, *, window=6):
        if not session_id or not self.p.authenticated or self.p.public_only:
            return
        self.p.require("memory:write")
        row = self._query().filter_by(session_id=session_id, kind="short", key="turns").first()
        turns = list(row.value.get("turns", [])) if row and row.expires_at > utcnow() else []
        turns.append(redact({"question": question[:2000], "answer": answer[:4000]}))
        overflow = turns[:-window]
        if overflow:
            summary = self._query().filter_by(session_id=session_id, kind="summary", key="conversation").first()
            prior = summary.value.get("text", "") if summary and summary.expires_at > utcnow() else ""
            # Extractive summaries preserve attribution and never create new assertions.
            excerpts = "\n".join(f"Q: {t['question'][:300]}\nA: {t['answer'][:700]}" for t in overflow)
            self.put("conversation", {"text": (prior + "\n" + excerpts)[-8000:], "method": "extractive-v1"},
                     kind="summary", session_id=session_id, ttl_seconds=604800,
                     expected_revision=summary.revision if summary else 0)
        self.put("turns", {"turns": turns[-window:]}, kind="short", session_id=session_id,
                 ttl_seconds=86400, expected_revision=row.revision if row else 0)

    def context(self, session_id):
        rows = self.read(session_id)
        preferences = {}
        for scope in ("tenant", "department"):
            if scope == "department" and not self.p.department_id:
                continue
            preferences.update({r.key: r.value for r in self.read(scope=scope) if r.kind == "long"})
        preferences.update({r.key: r.value for r in rows if r.kind == "long"})
        return {
            "preferences": preferences,
            "summary": next((r.value.get("text", "") for r in rows if r.kind == "summary"), ""),
            "turns": next((r.value.get("turns", []) for r in rows if r.kind == "short"), []),
        }


def purge_expired(db):
    p = principal_var.get()
    query = db.query(MemoryRecord).filter(MemoryRecord.expires_at <= utcnow())
    if p.authenticated:
        if p.public_only:
            raise HTTPException(403, "public-only tasks cannot delete enterprise memory")
        query = query.filter(
            MemoryRecord.tenant_id == p.tenant_id,
            or_(MemoryRecord.department_id == "", MemoryRecord.department_id == p.department_id),
            MemoryRecord.classification.in_([level.name for level in DataLevel if level <= p.clearance]),
        )
    return query.delete(synchronize_session=False)
