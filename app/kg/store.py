"""落图与图加载（G1）：networkx 在内存算，事实落关系表。

- `GraphStore.load()` 只把当前租户、且调用方可读密级内的节点与边读进内存图；
  不可读的数据根本不进入图，从源头避免"图遍历绕过密级"。
- `GraphStore.upsert()` 负责对齐、去重、写库，返回可审计的计数（新增/合并/跳过）。
- 单条关系由 `relation_key`（租户/头/类型/尾/来源）唯一，重复构图幂等。

图规模超出 `kg_max_nodes` 时加载会截断并在 `graph.graph["truncated"]` 标记——
截断是降级而不是静默：`community` 层会据此走社区摘要而不是继续钻节点。
"""
from __future__ import annotations

import hashlib

import networkx as nx
from sqlalchemy.orm import Session

from ..agent.governance import DataLevel, audit, principal_var
from ..config import settings
from .align import EntityAligner, canonical_key
from .models import KGCommunity, KGEntity, KGRelation


def node_id(entity) -> str:
    """内存图节点标识：类型 + 归一键，与数据库自增 id 解耦，便于跨版本比较。"""
    return f"{entity.entity_type}:{entity.norm_key}"


def relation_key(*, tenant_id: str, head_id: int, relation_type: str, tail_id: int, source_key: str = "") -> str:
    payload = f"{tenant_id}|{head_id}|{relation_type}|{tail_id}|{source_key}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:40]


def visible_levels(ceiling: DataLevel | None = None) -> list[str]:
    """当前调用方可读的密级集合；未认证的调用方只看到 public。"""
    principal = principal_var.get()
    if ceiling is None:
        ceiling = DataLevel.public if (not principal.authenticated or principal.public_only) else principal.clearance
    return [level.name for level in DataLevel if level <= ceiling]


class GraphStore:
    def __init__(self, db: Session, *, domain: str = "policy", tenant_id: str | None = None):
        self.db = db
        self.domain = domain
        self.tenant_id = tenant_id

    def scope(self) -> str:
        return self.tenant_id or principal_var.get().tenant_id or "default"

    # ---------- 读 ----------

    def _entity_rows(self, tenant_id: str, levels: list[str], limit: int):
        query = self.db.query(KGEntity).filter(KGEntity.tenant_id == tenant_id)
        if levels:
            query = query.filter(KGEntity.classification.in_(levels))
        return query.order_by(KGEntity.id).limit(limit).all()

    def load(self, *, tenant_id: str | None = None, ceiling: DataLevel | None = None,
             max_nodes: int | None = None) -> nx.MultiDiGraph:
        """加载可见子图；不加载的节点不会出现在遍历结果里。"""
        tenant = tenant_id or self.scope()
        limit = max(1, int(max_nodes or settings.kg_max_nodes))
        rows = self._entity_rows(tenant, visible_levels(ceiling), limit)
        graph = nx.MultiDiGraph(
            tenant=tenant, domain=self.domain, truncated=len(rows) >= limit,
            node_count=len(rows), relation_count=0, alignment_threshold=settings.kg_alignment_threshold,
        )
        by_id: dict[int, str] = {}
        for row in rows:
            identifier = node_id(row)
            by_id[row.id] = identifier
            graph.add_node(
                identifier, db_id=row.id, name=row.name, entity_type=row.entity_type,
                norm_key=row.norm_key, classification=row.classification,
                tenant_id=row.tenant_id, aliases=list(row.aliases or []),
                source_refs=list(row.source_refs or []), degree=row.degree,
                community_id=row.community_id,
            )
        if not by_id:
            return graph
        relations = (
            self.db.query(KGRelation)
            .filter(KGRelation.tenant_id == tenant, KGRelation.head_id.in_(list(by_id)))
            .order_by(KGRelation.id)
            .all()
        )
        for relation in relations:
            tail = by_id.get(relation.tail_id)
            if tail is None:
                continue
            graph.add_edge(
                by_id[relation.head_id], tail, key=relation.relation_key,
                relation_id=relation.id, relation=relation.relation_type,
                evidence=relation.evidence or "", source_ref=dict(relation.source_ref or {}),
                confidence=float(relation.confidence or 0.0), classification=relation.classification,
            )
            graph.graph["relation_count"] += 1
        return graph

    def known_entities(self, tenant_id: str | None = None) -> dict[str, dict[str, str]]:
        """给对齐器用的现有实体索引：类型 -> 归一键 -> 规范名。"""
        tenant = tenant_id or self.scope()
        index: dict[str, dict[str, str]] = {}
        for row in self.db.query(KGEntity).filter(KGEntity.tenant_id == tenant).all():
            index.setdefault(row.entity_type, {}).setdefault(row.norm_key, row.name)
        return index

    # ---------- 写 ----------

    def upsert(self, extraction: dict, *, tenant_id: str | None = None, classification: str = "public",
               department_id: str = "", source_key: str = "") -> dict:
        """把一次抽取结果写进图；同类型同名合并到同一节点，关系按唯一键幂等。"""
        tenant = tenant_id or self.scope()
        if classification not in DataLevel.__members__:
            raise ValueError("unknown data classification")
        aligner = EntityAligner(settings.kg_alignment_threshold, self.known_entities(tenant))
        stats = {
            "entitiesNew": 0, "entitiesMerged": 0, "entitiesUpdated": 0,
            "relationsNew": 0, "relationsSkipped": 0, "relationsReplaced": 0,
            "rejected": len(extraction.get("rejected") or []),
        }
        if source_key:
            # 覆盖式构图：同一来源重构图时先清掉旧边，保证"重复构图结果一致"，
            # 而不是把变化部分留成两套边（关系唯一键只能防重复，防不了替换）。
            stats["relationsReplaced"] = self.db.query(KGRelation).filter(
                KGRelation.tenant_id == tenant, KGRelation.source_key == source_key,
            ).delete(synchronize_session=False)
        resolved: dict[tuple[str, str], KGEntity] = {}
        for row in extraction.get("entities") or []:
            entity_type = str(row.get("type") or "")
            aligned = aligner.resolve(entity_type, str(row.get("name") or ""), row.get("aliases") or [])
            resolved[(entity_type, aligned.norm_key)] = self._persist_entity(
                tenant, classification, department_id, entity_type, aligned, row, source_key, stats,
            )
        for row in extraction.get("relations") or []:
            head_type, tail_type = str(row.get("headType") or ""), str(row.get("tailType") or "")
            head = resolved.get((head_type, canonical_key(str(row.get("head") or ""))))
            tail = resolved.get((tail_type, canonical_key(str(row.get("tail") or ""))))
            # validate 已保证端点同批存在；这里兜的是别名改写后键不一致的情况。
            head = head or self._find_entity(tenant, str(row.get("head") or ""), head_type)
            tail = tail or self._find_entity(tenant, str(row.get("tail") or ""), tail_type)
            if head is None or tail is None or head.id == tail.id:
                stats["relationsSkipped"] += 1
                continue
            key = relation_key(
                tenant_id=tenant, head_id=head.id, relation_type=str(row.get("type") or ""),
                tail_id=tail.id, source_key=source_key,
            )
            exists = self.db.query(KGRelation.id).filter(KGRelation.relation_key == key).first()
            if exists:
                stats["relationsSkipped"] += 1
                continue
            self.db.add(KGRelation(
                tenant_id=tenant, department_id=department_id, classification=classification,
                relation_key=key, source_key=source_key,
                head_id=head.id, tail_id=tail.id, relation_type=str(row.get("type") or ""),
                evidence=str(row.get("evidence") or "")[:2000],
                source_ref=dict(row.get("source_ref") or {}), confidence=float(row.get("confidence") or 1.0),
            ))
            stats["relationsNew"] += 1
        self.db.flush()
        audit(self.db, "kg.upsert", self.domain, details={"tenantId": tenant, **stats})
        return stats

    def _persist_entity(self, tenant, classification, department_id, entity_type, aligned, row, source_key, stats):
        entity = (
            self.db.query(KGEntity)
            .filter(KGEntity.tenant_id == tenant, KGEntity.entity_type == entity_type, KGEntity.norm_key == aligned.norm_key)
            .first()
        )
        ref = {"sourceKey": source_key, **dict(row.get("source_ref") or {})}
        if entity is None:
            entity = KGEntity(
                tenant_id=tenant, department_id=department_id, classification=classification,
                name=aligned.name, norm_key=aligned.norm_key, entity_type=entity_type,
                aliases=list(aligned.aliases or []), source_refs=[ref],
                merge_log=([{"reason": aligned.reason, "from": aligned.merged_from}] if aligned.merged_from else []),
            )
            self.db.add(entity)
            self.db.flush()
            stats["entitiesNew"] += 1
            return entity
        entity.aliases = list(dict.fromkeys([*(entity.aliases or []), *(aligned.aliases or [])]))
        refs = list(entity.source_refs or [])
        if ref not in refs:
            refs.append(ref)
        entity.source_refs = refs[:200]
        if aligned.merged_from:
            entity.merge_log = [*(entity.merge_log or []), {"reason": aligned.reason, "from": aligned.merged_from}][:200]
            stats["entitiesMerged"] += 1
        else:
            stats["entitiesUpdated"] += 1
        # 同一个节点被更高密级来源引用时取更高密级：宁可更严，不可更松。
        entity.classification = max(DataLevel[entity.classification], DataLevel[classification]).name
        entity.department_id = entity.department_id or department_id
        return entity

    def _find_entity(self, tenant: str, name: str, entity_type: str = "") -> KGEntity | None:
        key = canonical_key(name)
        if not key:
            return None
        query = self.db.query(KGEntity).filter(KGEntity.tenant_id == tenant, KGEntity.norm_key == key)
        if entity_type:
            query = query.filter(KGEntity.entity_type == entity_type)
        return query.order_by(KGEntity.id).first()

    def refresh_degrees(self, tenant_id: str | None = None) -> int:
        """重算节点度数（构图后调用一次，供社区检测与遍历排序使用）。"""
        tenant = tenant_id or self.scope()
        rows = self.db.query(KGEntity).filter(KGEntity.tenant_id == tenant).all()
        degrees: dict[int, int] = {row.id: 0 for row in rows}
        for head_id, tail_id in self.db.query(KGRelation.head_id, KGRelation.tail_id).filter(
            KGRelation.tenant_id == tenant
        ).all():
            if head_id in degrees:
                degrees[head_id] += 1
            if tail_id in degrees:
                degrees[tail_id] += 1
        for row in rows:
            row.degree = degrees.get(row.id, 0)
        self.db.flush()
        return len(rows)

    def replace_communities(self, communities: list[dict], *, tenant_id: str | None = None,
                            classification: str = "public") -> list[int]:
        """整批替换社区摘要：重复写入不会累积垃圾行；返回新社区行 id 供回写归属。"""
        tenant = tenant_id or self.scope()
        self.db.query(KGCommunity).filter(
            KGCommunity.tenant_id == tenant, KGCommunity.domain == self.domain
        ).delete(synchronize_session=False)
        ids: list[int] = []
        for row in communities:
            entity_ids = list(row.get("entityIds") or [])
            record = KGCommunity(
                tenant_id=tenant, classification=classification, domain=self.domain,
                level=int(row.get("level") or 0), signature=str(row.get("signature") or ""),
                size=len(entity_ids), entity_ids=entity_ids, summary=str(row.get("summary") or ""),
                model=str(row.get("model") or ""), source=str(row.get("source") or "rule"),
            )
            self.db.add(record)
            self.db.flush()
            ids.append(record.id)
        audit(self.db, "kg.community", self.domain, details={"tenantId": tenant, "count": len(ids)})
        return ids

    def stats(self, tenant_id: str | None = None) -> dict:
        tenant = tenant_id or self.scope()
        return {
            "entities": self.db.query(KGEntity).filter(KGEntity.tenant_id == tenant).count(),
            "relations": self.db.query(KGRelation).filter(KGRelation.tenant_id == tenant).count(),
            "communities": self.db.query(KGCommunity).filter(
                KGCommunity.tenant_id == tenant, KGCommunity.domain == self.domain
            ).count(),
        }
