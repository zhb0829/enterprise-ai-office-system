"""图召回（G1）：查询实体链接 → 多跳遍历 → 条款候选，供现有 RRF 做第三路融合。

三条纪律：

- **只给信号，不改主链路**：输出是条款的排序信号与解释路径，最终顺序仍由现有
  BM25 + Dense + RRF + 精排决定；图路异常退化为 `degraded`，不让问答失败。
- **可解释**：每条命中带完整路径（经过哪些实体、哪些关系、几跳），可直接进审计与引用。
- **不越权**：加载图时先按租户与密级过滤，命中再按 `Principal.can_read` 复核一次。

口径提醒：图召回不做语义推断，只沿白名单关系走；图上没有的事实它给不出来。
"""
from __future__ import annotations

from ..agent.governance import DataLevel, principal_var
from ..config import settings
from .align import canonical_key, name_similarity, normalize_name
from .models import KGCommunity
from .store import GraphStore
from .traverse import clause_hits, multi_hop, node_summary

_QUERY_GRAM_MIN = 2
_QUERY_GRAM_MAX = 12
_QUERY_GRAM_LIMIT = 800
_LINK_SIMILARITY_FLOOR = 0.7
_LINK_MIN_OVERLAP = 3   # 片段与实体名至少 3 字重叠才比较，避免共同前缀把不同文件连起来


def clause_key_for(*, doc_id, article_no: str = "", parent_key: str = "") -> str:
    """条款键：构图与检索共用同一套键，避免两边各算一套导致对不上。"""
    return f"policy:{doc_id}#{article_no or ''}#{parent_key or ''}"


def clause_identities(clause) -> list[tuple]:
    """一个候选条款可能被图命中的三种键：条款 id、文档 id+条款号、稳定条款键。"""
    identities: list[tuple] = []
    clause_id = getattr(clause, "id", None)
    if clause_id is not None:
        identities.append(("id", int(clause_id)))
    doc_id = getattr(clause, "doc_id", None)
    if doc_id is not None:
        article_no = str(getattr(clause, "article_no", "") or "")
        identities.append(("article", int(doc_id), article_no))
        meta = getattr(clause, "meta", None) or {}
        identities.append(("key", clause_key_for(
            doc_id=doc_id, article_no=article_no, parent_key=meta.get("parent_key", ""),
        )))
    return identities


def rank_clause_indices(hits: list[dict], clauses: list) -> list[int]:
    """把图命中映射成候选下标；顺序即图这一路的排名信号，交给 RRF 融合。"""
    lookup: dict[tuple, int] = {}
    for index, clause in enumerate(clauses):
        for identity in clause_identities(clause):
            lookup.setdefault(identity, index)
    ordered: list[int] = []
    seen: set[int] = set()
    for hit in hits:
        index = lookup.get(hit.get("identity"))
        if index is None or index in seen:
            continue
        seen.add(index)
        ordered.append(index)
    return ordered


def _query_grams(text: str) -> list[str]:
    grams: list[str] = []
    for size in range(_QUERY_GRAM_MIN, _QUERY_GRAM_MAX + 1):
        grams.extend(text[index : index + size] for index in range(max(0, len(text) - size + 1)))
    return grams[:_QUERY_GRAM_LIMIT]


def link_nodes_scored(graph, query: str, *, limit: int = 8) -> list[tuple[float, str]]:
    """查询实体链接：整体包含命中优先（名字越具体分越高），其次按片段相似度兜。"""
    normalized = normalize_name(query)
    if not normalized:
        return []
    grams = _query_grams(normalized)
    scored: list[tuple[float, str]] = []
    for node, data in graph.nodes(data=True):
        key = canonical_key(str(data.get("name") or ""))
        if not key:
            continue
        score = 0.0
        if key in normalized:
            score = 1.0 + len(key) / max(len(normalized), 1)
        else:
            for gram in grams:
                if min(len(gram), len(key)) < _LINK_MIN_OVERLAP:
                    continue
                similarity = name_similarity(gram, key)
                if similarity >= _LINK_SIMILARITY_FLOOR:
                    score = max(score, similarity)
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[: max(1, int(limit))]


def link_nodes(graph, query: str, *, limit: int = 8) -> list[str]:
    """只要节点标识的兼容入口。"""
    return [node for _, node in link_nodes_scored(graph, query, limit=limit)]


def hit_relevance(graph, hit: dict, seed_scores: dict[str, float], normalized_query: str) -> float:
    """命中条款的相关度：起点实体与问题的贴合度 + 路径上被问题点名的节点 + 跳数衰减。

    只看跳数会让"与问题无关但相邻"的条款排到前面；把实体贴合度放第一位，
    图的排序信号才对得上"关系推理"这个应用场景。
    """
    path = hit.get("path") or []
    best_seed = max((float(seed_scores.get(str(step.get("from")), 0.0)) for step in path), default=0.0)
    mentioned = 0.0
    if normalized_query:
        for step in path:
            for node in (step.get("from"), step.get("to")):
                name = canonical_key(str((graph.nodes.get(node) or {}).get("name") or ""))
                if name and name in normalized_query:
                    mentioned = max(mentioned, min(1.0, len(name) / max(len(normalized_query), 1) * 4))
    return round(0.6 * best_seed + mentioned + 1.0 / (1.0 + int(hit.get("hops") or 1)), 6)


def community_evidence(
    db, tenant_id: str, graph, seeds: list[str], *, domain: str = "policy", limit: int = 3,
) -> list[dict]:
    """与命中实体同社区的摘要：全局性问题先看社区，不急着钻节点。"""
    db_ids = sorted({
        int(graph.nodes[node]["db_id"])
        for node in seeds
        if node in graph and graph.nodes[node].get("db_id") is not None
    })
    return community_rows(db, tenant_id, domain, db_ids, limit)


def community_rows(db, tenant_id: str, domain: str, db_ids: list[int], limit: int) -> list[dict]:
    """按与给定实体集合的重叠度返回社区摘要；无重叠不返回，不硬凑。"""
    if not db_ids:
        return []
    wanted = set(db_ids)
    matches: list[dict] = []
    rows = db.query(KGCommunity).filter(
        KGCommunity.tenant_id == tenant_id, KGCommunity.domain == domain
    ).order_by(KGCommunity.id).all()
    for row in rows:
        members = set(row.entity_ids or [])
        overlap = len(members & wanted)
        if not overlap:
            continue
        matches.append({
            "id": row.id, "summary": row.summary, "size": row.size,
            "source": row.source, "overlap": overlap, "signature": row.signature,
        })
    matches.sort(key=lambda item: (-item["overlap"], -item["size"], item["id"]))
    return matches[: max(1, int(limit))]


def graph_search(
    db,
    query: str,
    *,
    domain: str = "policy",
    tenant_id: str | None = None,
    limit: int = 20,
    max_hops: int | None = None,
    ceiling: DataLevel | None = None,
    include_communities: bool = True,
) -> dict:
    """图召回主入口；返回结构固定，便于审计与"纯向量 vs 向量+图"对比。"""
    hops = int(max_hops or settings.kg_max_hops)
    store = GraphStore(db, domain=domain, tenant_id=tenant_id)
    tenant = tenant_id or store.scope()
    graph = store.load(tenant_id=tenant, ceiling=ceiling)
    payload = {
        "domain": domain, "tenantId": tenant, "maxHops": hops,
        "graph": {
            "nodes": graph.number_of_nodes(),
            "relations": int(graph.graph.get("relation_count", 0)),
            "truncated": bool(graph.graph.get("truncated", False)),
        },
        "degraded": False, "seeds": [], "hits": [], "communities": [],
    }
    linked = link_nodes_scored(graph, query, limit=settings.kg_seed_limit)
    seeds = [node for _, node in linked]
    if not seeds:
        return payload
    seed_scores = dict(linked)
    traversed = multi_hop(graph, seeds, max_hops=hops, limit=max(int(limit) * 3, 30))
    hits = clause_hits(graph, traversed, max_hits=max(1, int(limit)))
    normalized = normalize_name(query)
    principal = principal_var.get()
    visible_hits: list[dict] = []
    for hit in hits:
        classification = str((graph.nodes.get(hit.get("node")) or {}).get("classification") or "public")
        if principal.authenticated and not principal.can_read(classification, tenant, "", ""):
            continue
        visible_hits.append({
            **hit,
            "identityKey": str(hit.get("identity")),
            "classification": classification,
            "relevance": hit_relevance(graph, hit, seed_scores, normalized),
        })
    # 图这一路的排序信号：先看与问题实体的贴合度，再看跳数——跳数少但与问题无关不该排前面。
    visible_hits.sort(key=lambda item: (-item["relevance"], item["hops"], str(item.get("identityKey"))))
    payload["seeds"] = [node_summary(graph, node) for node in seeds]
    payload["hits"] = visible_hits
    if include_communities:
        payload["communities"] = community_evidence(db, tenant, graph, seeds, domain=domain, limit=3)
    return payload
