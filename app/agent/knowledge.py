from __future__ import annotations

import copy
import uuid
from datetime import datetime
from threading import RLock

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .governance import DataLevel, audit, classified_data, principal_var, utc_naive, utcnow
from .platform_models import KnowledgeEntry, KnowledgeHead, KnowledgeRelease
from .runtime import digest


def namespace_for(domain, *, public=False):
    if domain not in {"policy", "materials", "opinion", "meeting"}:
        raise HTTPException(422, "unknown knowledge domain")
    if public:
        return f"public:{domain}"
    tenant = principal_var.get().tenant_id or "default"
    return f"tenant:{tenant}:{domain}"


class KnowledgeStore:
    """Immutable releases with a database generation fence shared by all workers."""
    _cache = {}
    _lock = RLock()

    def __init__(self, db: Session, namespace: str):
        self.db, self.namespace = db, namespace

    def active(self, at: datetime | None = None):
        at = utc_naive(at) or utcnow()
        return self.db.query(KnowledgeRelease).filter(
            KnowledgeRelease.namespace == self.namespace, KnowledgeRelease.status == "published",
            KnowledgeRelease.effective_at <= at,
            (KnowledgeRelease.expires_at.is_(None) | (KnowledgeRelease.expires_at > at)),
        ).order_by(KnowledgeRelease.effective_at.desc(), KnowledgeRelease.version.desc()).first()

    def stage(self, documents: list[dict], *, deleted_keys=(), effective_at=None, expires_at=None, expected_generation=None):
        effective_at, expires_at = utc_naive(effective_at) or utcnow(), utc_naive(expires_at)
        if expires_at and expires_at <= effective_at:
            raise HTTPException(422, "invalid knowledge validity interval")
        keys = [item["key"] for item in documents]
        if len(keys) != len(set(keys)) or set(keys) & set(deleted_keys):
            raise HTTPException(422, "duplicate or conflicting document keys")
        head = self.db.get(KnowledgeHead, self.namespace, populate_existing=True)
        if head is None:
            head = KnowledgeHead(namespace=self.namespace, generation=0, next_version=1)
            self.db.add(head)
            self.db.flush()
        generation = head.generation
        if expected_generation is not None and generation != expected_generation:
            raise HTTPException(409, "knowledge generation conflict")
        version = head.next_version
        reserved = self.db.execute(update(KnowledgeHead).where(
            KnowledgeHead.namespace == self.namespace, KnowledgeHead.next_version == version,
        ).values(next_version=version + 1))
        if reserved.rowcount != 1:
            raise HTTPException(409, "concurrent knowledge staging")
        parent = self.active()
        previous = {e.key: e for e in self.db.query(KnowledgeEntry).filter_by(release_id=parent.id).all()} if parent else {}
        p = principal_var.get()
        if p.authenticated:
            for key in set(keys) | set(deleted_keys):
                old = previous.get(key)
                if old and not p.can_read(old.classification, old.tenant_id, old.department_id, old.owner_id):
                    raise HTTPException(403, "knowledge document is outside the trusted data scope")
        manifest = {key: self._data(row) for key, row in previous.items() if key not in deleted_keys}
        stats = {"added": 0, "updated": 0, "unchanged": 0, "deleted": len(set(deleted_keys) & set(previous)),
                 "base_generation": generation}
        for item in documents:
            item = copy.deepcopy(item)
            level = item.get("classification", "public")
            if level not in DataLevel.__members__:
                raise HTTPException(422, "unknown data classification")
            if self.namespace.startswith("public:") and level != "public":
                raise HTTPException(422, "private information cannot enter a public knowledge namespace")
            tenant = item.get("tenant_id", "")
            if level != "public" and (not tenant or self.namespace != f"tenant:{tenant}:{self.namespace.rsplit(':', 1)[-1]}"):
                raise HTTPException(422, "knowledge tenant boundary mismatch")
            if p.authenticated and not p.can_read(
                level, tenant, item.get("department_id", ""), item.get("owner_id", ""),
            ):
                raise HTTPException(403, "knowledge classification is outside the trusted data scope")
            start, end = utc_naive(item.get("effective_at")), utc_naive(item.get("expires_at"))
            if start and end and end <= start:
                raise HTTPException(422, "invalid document validity interval")
            chunks = item.get("chunks", [])
            if not chunks:
                from ..config import settings
                from ..services.materials import CHUNKING_VERSION, chunk_metadata, embed_texts, embedding_info, split_text_chunks
                content_key = digest({"text": item.get("text", ""), "metadata": item.get("metadata", {}),
                                      "classification": level, "tenant": tenant, "department": item.get("department_id", ""),
                                      "owner": item.get("owner_id", ""), "start": start, "end": end,
                                      "chunking_version": CHUNKING_VERSION,
                                      "semantic": settings.chunk_semantic_enabled,
                                      "trigger": settings.chunk_semantic_trigger_size,
                                      "min_size": settings.chunk_min_size,
                                      "threshold": settings.chunk_semantic_similarity_threshold})
                if item["key"] in previous and previous[item["key"]].content_hash == content_key:
                    stats["unchanged"] += 1
                    continue
                with classified_data(level):
                    semantic_embedder = (
                        embed_texts if settings.chunk_semantic_enabled and settings.embedding_api_key and settings.embedding_model
                        else None
                    )
                    split_chunks = split_text_chunks(
                        item.get("text", ""),
                        semantic=semantic_embedder is not None,
                        embedder=semantic_embedder,
                    )
                    texts = [chunk.text for chunk in split_chunks]
                    vectors = embed_texts(texts)
                chunks = [
                    {
                        "text": chunk.text,
                        "embedding": vector,
                        "meta": {
                            **embedding_info(vector),
                            **chunk_metadata(chunk),
                        },
                    }
                    for chunk, vector in zip(split_chunks, vectors)
                ]
            else:
                content_key = digest({**item, "effective_at": start, "expires_at": end})
                if item["key"] in previous and previous[item["key"]].content_hash == content_key:
                    stats["unchanged"] += 1
                    continue
            stats["updated" if item["key"] in previous else "added"] += 1
            manifest[item["key"]] = dict(
                key=item["key"], content_hash=content_key, chunks=chunks, metadata_=item.get("metadata", {}),
                classification=level, tenant_id=tenant, department_id=item.get("department_id", ""),
                owner_id=item.get("owner_id", ""), effective_at=start, expires_at=end,
            )
        release = KnowledgeRelease(
            id=uuid.uuid4().hex, namespace=self.namespace, version=version, parent_id=parent.id if parent else None,
            status="staged", effective_at=effective_at, expires_at=expires_at,
            manifest_hash=digest(manifest), changes=stats,
        )
        self.db.add(release)
        self.db.flush()
        for data in manifest.values():
            self.db.add(KnowledgeEntry(release_id=release.id, **data))
        audit(self.db, "knowledge.stage", self.namespace, details={"releaseId": release.id, **stats})
        self.db.flush()
        return release

    @staticmethod
    def _data(row):
        return {column.key: getattr(row, column.key) for column in KnowledgeEntry.__mapper__.column_attrs if column.key != "release_id"}

    def discard(self, row):
        self.db.query(KnowledgeEntry).filter_by(release_id=row.id).delete(synchronize_session=False)
        self.db.delete(row)

    def publish(self, release_id):
        row = self.db.get(KnowledgeRelease, release_id)
        if not row or row.namespace != self.namespace:
            raise HTTPException(404, "knowledge release not found")
        if row.status != "staged":
            raise HTTPException(409, "only staged releases can be published")
        pending = self.db.query(KnowledgeRelease).filter(
            KnowledgeRelease.namespace == self.namespace,
            KnowledgeRelease.status == "published",
            KnowledgeRelease.effective_at > utcnow(),
        ).first()
        if pending:
            raise HTTPException(409, "scheduled release exists; cancel or rollback before publishing another release")
        generation = row.changes["base_generation"]
        result = self.db.execute(update(KnowledgeHead).where(
            KnowledgeHead.namespace == self.namespace, KnowledgeHead.generation == generation,
        ).values(release_id=row.id, generation=generation + 1))
        if result.rowcount != 1:
            raise HTTPException(409, "knowledge head changed; rebase before publishing")
        row.status = "published"
        audit(self.db, "knowledge.publish", self.namespace, details={"releaseId": row.id, "version": row.version})
        self.db.flush()
        return row

    def rollback(self, release_id):
        source = self.db.get(KnowledgeRelease, release_id)
        if not source or source.namespace != self.namespace or source.status != "published":
            raise HTTPException(404, "published release not found")
        source_entries = self.db.query(KnowledgeEntry).filter_by(release_id=source.id).all()
        active = self.active()
        current_keys = {row.key for row in self.db.query(KnowledgeEntry).filter_by(release_id=active.id)} if active else set()
        documents = [{**self._data(r), "metadata": r.metadata_} for r in source_entries]
        # Pending scheduled releases must not silently undo an explicit rollback.
        for pending in self.db.query(KnowledgeRelease).filter(
            KnowledgeRelease.namespace == self.namespace, KnowledgeRelease.status == "published",
            KnowledgeRelease.effective_at > utcnow(),
        ):
            pending.status = "cancelled"
        row = self.stage(documents, deleted_keys=current_keys - {r.key for r in source_entries})
        row.changes = {**row.changes, "rollback_of": release_id}
        return self.publish(row.id)

    def snapshot(self, at=None, *, principal=None):
        at = utc_naive(at) or utcnow()
        row = self.active(at)
        if not row:
            return {"releaseId": None, "version": None, "generation": 0, "entries": []}
        generation = self.db.scalar(select(KnowledgeHead.generation).where(KnowledgeHead.namespace == self.namespace)) or 0
        key = (self.db.get_bind(), self.namespace, row.id, generation)
        with self._lock:
            entries = self._cache.get(key)
        if entries is None:
            entries = [self._data(r) for r in self.db.query(KnowledgeEntry).filter_by(release_id=row.id).all()]
            with self._lock:
                if len(self._cache) >= 128:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = copy.deepcopy(entries)
        from .access import filter_visible
        p = principal or principal_var.get()
        in_window = [r for r in entries if (not r["effective_at"] or r["effective_at"] <= at)
                     and (not r["expires_at"] or r["expires_at"] > at)]
        # 与检索共用同一道判定：未知密级按不可读处理，不能让它把 KeyError 变成 500。
        visible, _rejected = filter_visible(
            in_window, p,
            level_of=lambda row: row["classification"], tenant_of=lambda row: row["tenant_id"],
            department_of=lambda row: row["department_id"], owner_of=lambda row: row["owner_id"],
        )
        return {"releaseId": row.id, "version": row.version, "generation": generation,
                "entries": copy.deepcopy(visible)}


def sync_document(db, domain, document, *, public=False):
    store = KnowledgeStore(db, namespace_for(domain, public=public))
    row = store.stage([document])
    # Legacy uploads remain immediately visible, but their history is now immutable.
    if row.changes["added"] or row.changes["updated"]:
        store.publish(row.id)
    else:
        store.discard(row)
    return row


def search_knowledge(db, domain, query, *, public=False, at=None, limit=6):
    from ..services.materials import embed_text, embedding_is_compatible, _cosine
    from .retrieval import bm25_scores
    snapshot = KnowledgeStore(db, namespace_for(domain, public=public)).snapshot(at)
    candidates = [(entry, index, chunk) for entry in snapshot["entries"] for index, chunk in enumerate(entry["chunks"])]
    lexical = bm25_scores(query, [chunk["text"] for _, _, chunk in candidates])
    vector = embed_text(query) if candidates else []
    results = []
    for (entry, index, chunk), score in zip(candidates, lexical):
        dense = _cosine(vector, chunk.get("embedding", [])) if embedding_is_compatible(chunk.get("meta"), vector) else 0
        if score <= 0 and dense < 0.35:
            continue
        meta = chunk.get("meta") or {}
        results.append({
            "key": entry["key"], "chunkIndex": index, "text": chunk["text"], "metadata": entry["metadata_"],
            "classification": entry["classification"], "score": float(score) + dense,
            "releaseId": snapshot["releaseId"], "knowledgeVersion": snapshot["version"],
            "meta": meta,
            "parentText": meta.get("parent_text") or chunk["text"],
            # G7：租户 / 部门 / 属主随结果带出，供末条 filter 复核并写入审计。
            "tenantId": entry["tenant_id"], "departmentId": entry["department_id"],
            "ownerId": entry["owner_id"],
        })
    results.sort(key=lambda row: row["score"], reverse=True)
    deduplicated = []
    seen = set()
    for row in results:
        meta = row["meta"]
        parent_key = meta.get("parent_key", meta.get("parent_chunk_index", row["chunkIndex"]))
        key = (row["key"], parent_key)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(row)
        if len(deduplicated) >= max(1, min(limit, 20)):
            break
    from .access import access_diagnostics, filter_visible
    principal = principal_var.get()
    # G7 检索末条 filter：快照已按身份过滤一次，结果出站前再按角色 / 租户 / 密级 / 部门 / 属主复核一次。
    visible, rejected = filter_visible(
        deduplicated, principal,
        level_of=lambda row: row["classification"], tenant_of=lambda row: row["tenantId"],
        department_of=lambda row: row["departmentId"], owner_of=lambda row: row["ownerId"],
    )
    from .governance import data_level_var
    for row in visible:
        data_level_var.set(max(data_level_var.get(), DataLevel[row["classification"]]))
    audit(db, "knowledge.search", domain, details={
        "releaseId": snapshot["releaseId"], "count": len(visible), "filtered": rejected,
        "access": access_diagnostics(principal, filtered=rejected),
    })
    return visible
