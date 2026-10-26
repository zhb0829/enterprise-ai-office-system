"""社区检测与社区摘要（G1）。

社区用于全局性问题（"这批政策整体在管什么"）：先读社区摘要，避免每次都从底层节点钻。
三条纪律：

- **可复现**：Louvain 固定 `seed`，输入图按节点名排序构造，同一份数据两次检测结果一致。
- **不撒谎**：摘要优先用抽取模型，无 Key 时用规则化摘要并标记 `source=rule`；模型失败退回
  `rule-fallback`，不把规则化文本冒充模型结论。
- **有归属**：社区行写入后把 `community_id` 回写到实体，检索侧才能"先社区后节点"。
"""
from __future__ import annotations

import hashlib
import json

import networkx as nx

from ..config import settings
from ..services.llm import LLMClient, LLMError
from .models import KGEntity
from .schema import ENTITY_TYPES, RELATION_TYPES
from .store import GraphStore

SUMMARY_ENTITY_LIMIT = 40
SUMMARY_RELATION_LIMIT = 60
MAX_COMMUNITIES = 64


def _undirected(graph: nx.MultiDiGraph) -> nx.Graph:
    """把多重有向图压成带权无向图，节点按名排序保证构造顺序确定。"""
    plain = nx.Graph()
    for node in sorted(graph.nodes):
        plain.add_node(node)
    for head, tail in sorted((str(u), str(v)) for u, v in graph.edges()):
        if plain.has_edge(head, tail):
            plain[head][tail]["weight"] += 1
        else:
            plain.add_edge(head, tail, weight=1)
    return plain


def detect_communities(
    graph: nx.MultiDiGraph, *, min_size: int = 3, seed: int = 42, max_communities: int = MAX_COMMUNITIES,
) -> list[dict]:
    """Louvain 社区检测；小于 `min_size` 的社区不单独成行（避免碎片摘要）。"""
    if graph.number_of_nodes() == 0:
        return []
    groups = nx.community.louvain_communities(_undirected(graph), weight="weight", seed=seed)
    communities: list[dict] = []
    for group in groups:
        nodes = sorted(str(node) for node in group)
        if len(nodes) < max(2, int(min_size)):
            continue
        members = set(nodes)
        relations = sorted({
            str(data.get("relation") or "")
            for head, tail, data in graph.edges(nodes, data=True)
            if head in members and tail in members and data.get("relation")
        })
        communities.append({"nodes": nodes, "relations": relations, "size": len(nodes)})
    communities.sort(key=lambda row: (-row["size"], row["nodes"][0]))
    return communities[: max(1, int(max_communities))]


def community_signature(nodes: list[str], relations: list[str]) -> str:
    payload = json.dumps({"nodes": sorted(nodes), "relations": sorted(relations)}, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:32]


def rule_summary(graph: nx.MultiDiGraph, nodes: list[str], relations: list[str]) -> str:
    """规则化摘要：只陈述社区里实际有什么，不做推断。"""
    by_type: dict[str, list[str]] = {}
    for node in nodes:
        data = graph.nodes.get(node) or {}
        by_type.setdefault(str(data.get("entity_type") or "未知"), []).append(str(data.get("name") or node))
    parts = [
        f"{ENTITY_TYPES.get(entity_type, entity_type)}{len(names)}项（{ '、'.join(sorted(names)[:6]) }）"
        for entity_type, names in sorted(by_type.items())
    ]
    labels = "、".join(RELATION_TYPES[item].label for item in sorted(relations) if item in RELATION_TYPES)
    return f"本社区含 {len(nodes)} 个实体：{'；'.join(parts)}。主要关系：{labels or '无'}。"


def llm_summary(graph: nx.MultiDiGraph, nodes: list[str], relations: list[str], llm: LLMClient, model: str) -> str:
    members = set(nodes)
    entity_lines = [
        f"{graph.nodes[node].get('entity_type')}: {graph.nodes[node].get('name')}" for node in nodes[:SUMMARY_ENTITY_LIMIT]
    ]
    relation_lines = sorted({
        f"{graph.nodes[head].get('name')} -{data.get('relation')}-> {graph.nodes[tail].get('name')}"
        for head, tail, data in graph.edges(nodes, data=True)
        if head in members and tail in members
    })
    system = (
        "你是政策知识图谱的社区摘要器。只依据给定的实体与关系写 2-3 句中文摘要，"
        "不得引入外部知识，不得推测未给出的事实；写不出来就直说信息不足。"
    )
    user = (
        "实体：\n" + "\n".join(entity_lines)
        + "\n关系：\n" + "\n".join(relation_lines[:SUMMARY_RELATION_LIMIT])
        + f"\n关系类型：{'、'.join(sorted(relations))}"
    )
    return str(llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                        model=model, temperature=0, purpose="kg.community") or "").strip()


def build_communities(
    db,
    graph: nx.MultiDiGraph,
    *,
    tenant_id: str,
    classification: str = "public",
    domain: str = "policy",
    llm: LLMClient | None = None,
) -> dict:
    """检测 + 摘要 + 落库 + 回写归属；返回计数与来源口径。"""
    min_size = settings.kg_community_min_size
    detected = detect_communities(graph, min_size=min_size)
    llm = llm if llm is not None else LLMClient()
    model = settings.kg_model or settings.llm_model_extraction
    rows: list[dict] = []
    sources: dict[str, int] = {}
    for community in detected:
        nodes, relations = community["nodes"], community["relations"]
        source, used_model = "rule", ""
        summary = rule_summary(graph, nodes, relations)
        if not llm.is_mock:
            try:
                generated = llm_summary(graph, nodes, relations, llm, model)
                if generated:
                    summary, source, used_model = generated, "llm", model
            except (LLMError, ValueError, TypeError, AttributeError):
                source = "rule-fallback"
        sources[source] = sources.get(source, 0) + 1
        rows.append({
            "level": 0,
            "signature": community_signature(nodes, relations),
            "entityIds": [graph.nodes[node]["db_id"] for node in nodes],
            "summary": summary, "source": source, "model": used_model, "nodes": nodes,
        })
    store = GraphStore(db, domain=domain, tenant_id=tenant_id)
    ids = store.replace_communities(rows, tenant_id=tenant_id, classification=classification)
    assignment = {
        graph.nodes[node]["db_id"]: community_id
        for row, community_id in zip(rows, ids)
        for node in row["nodes"]
    }
    if assignment:
        for entity in db.query(KGEntity).filter(KGEntity.id.in_(list(assignment))).all():
            entity.community_id = assignment[entity.id]
        db.flush()
    return {
        "detected": len(detected), "written": len(ids), "minSize": min_size,
        "sources": sources, "model": model if not llm.is_mock else "",
        "sizes": [row["size"] for row in detected],
    }
