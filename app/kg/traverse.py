"""多跳遍历（G1）：从命中实体出发做受限 BFS，产出可回溯路径。

图里本来就只允许 Schema 白名单关系，遍历不再二次过滤类型；真正要防的是爆炸：
每次扩展有 `per_hop_limit` 上限，路径按 (from, relation, to) 去重，结果按跳数与分数排序。

返回值固定带完整路径（节点名 + 关系 + 中文标签 + 证据），回答"为什么召回这条"时
直接可用，而不是给一个说不清来源的节点列表。
"""
from __future__ import annotations

import networkx as nx

from .schema import RELATION_TYPES

MAX_PER_HOP = 200
_MAX_RESULTS_FACTOR = 6


def relation_label(relation_type: str) -> str:
    spec = RELATION_TYPES.get(relation_type)
    return spec.label if spec else str(relation_type)


def node_summary(graph: nx.MultiDiGraph, node: str) -> dict:
    data = graph.nodes.get(node) or {}
    return {
        "node": node,
        "name": data.get("name", node),
        "entityType": data.get("entity_type", ""),
    }


def _expansions(graph: nx.MultiDiGraph, node: str) -> list[tuple[str, str, str, dict]]:
    """一个节点的邻接展开，顺序确定：先出边后入边，各自按关系类型与邻居排序。"""
    expansions: list[tuple[str, str, str, dict]] = []
    out_edges = sorted(
        graph.out_edges(node, keys=True, data=True),
        key=lambda item: (str(item[3].get("relation") or ""), item[1], str(item[2])),
    )
    for _, neighbor, _, data in out_edges:
        expansions.append((neighbor, str(data.get("relation") or ""), "out", data))
    in_edges = sorted(
        graph.in_edges(node, keys=True, data=True),
        key=lambda item: (str(item[3].get("relation") or ""), item[0], str(item[2])),
    )
    for neighbor, _, _, data in in_edges:
        expansions.append((neighbor, str(data.get("relation") or ""), "in", data))
    return expansions


def multi_hop(
    graph: nx.MultiDiGraph,
    seeds: list[str],
    *,
    max_hops: int = 2,
    limit: int = 50,
    per_hop_limit: int = MAX_PER_HOP,
) -> list[dict]:
    """受限 BFS：返回 [{node, name, entityType, hops, score, path}]。"""
    max_hops = max(1, int(max_hops))
    limit = max(1, int(limit))
    results: list[dict] = []
    seen_paths: set[tuple] = set()
    visited: set[str] = {seed for seed in seeds if seed in graph}
    frontier: list[tuple[str, list[dict]]] = [(seed, []) for seed in seeds if seed in graph]
    if not frontier or graph.number_of_nodes() == 0:
        return results
    seen_paths.update((seed, "", "") for seed in visited)
    for _ in range(max_hops):
        next_frontier: list[tuple[str, list[dict]]] = []
        for node, path in frontier:
            taken = 0
            for neighbor, relation_type, direction, data in _expansions(graph, node):
                if taken >= per_hop_limit:
                    break
                taken += 1
                step = {
                    "from": node, "to": neighbor, "relation": relation_type,
                    "label": relation_label(relation_type), "direction": direction,
                    "evidence": str(data.get("evidence") or ""),
                }
                signature = tuple((item["from"], item["relation"], item["to"]) for item in [*path, step])
                if signature in seen_paths:
                    continue
                seen_paths.add(signature)
                hops = len(path) + 1
                summary = node_summary(graph, neighbor)
                results.append({
                    **summary, "hops": hops,
                    "score": round(1.0 / (1.0 + hops), 6),
                    "path": [*path, step],
                })
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_frontier.append((neighbor, [*path, step]))
        frontier = next_frontier
        if not frontier or len(results) >= limit * _MAX_RESULTS_FACTOR:
            break
    results.sort(key=lambda row: (row["hops"], -row["score"], row["node"]))
    return results[:limit]


def clause_identity(ref: dict) -> tuple | None:
    """把来源引用还原成可用于对齐条款的键；三项都缺则视为不可定位。"""
    if not isinstance(ref, dict):
        return None
    clause_id = ref.get("clauseId")
    if clause_id is not None and str(clause_id).lstrip("-").isdigit():
        return ("id", int(clause_id))
    doc_id = ref.get("docId")
    if doc_id is not None and str(doc_id).lstrip("-").isdigit():
        return ("article", int(doc_id), str(ref.get("articleNo") or ""))
    if ref.get("clauseKey"):
        return ("key", str(ref["clauseKey"]))
    return None


def clause_hits(
    graph: nx.MultiDiGraph,
    results: list[dict],
    *,
    clause_types: tuple[str, ...] = ("Clause",),
    max_hits: int = 50,
) -> list[dict]:
    """把遍历结果里的条款节点还原成条款候选，保留最短路径作为解释。

    只认 `Clause`：`Policy` 节点的来源引用混入了"被别的条文引用"的情况
    （`basedOn` 的被引用方就是从引用条文里抽出来的），拿它的 source_refs 当条款归属，
    会把 A 文件被引用的位置算成 B 文件的条款。
    """
    best: dict[tuple, dict] = {}
    for row in results:
        data = graph.nodes.get(row["node"]) or {}
        if data.get("entity_type") not in clause_types:
            continue
        for ref in data.get("source_refs") or []:
            identity = clause_identity(ref)
            if identity is None:
                continue
            candidate = {
                "identity": identity, "clauseId": ref.get("clauseId"),
                "docId": ref.get("docId"), "articleNo": ref.get("articleNo") or "",
                "parentKey": ref.get("parentKey") or "", "clauseKey": ref.get("clauseKey") or "",
                "node": row["node"], "name": row.get("name", ""), "entityType": row.get("entityType", ""),
                "hops": row["hops"], "score": row["score"], "path": row["path"],
            }
            current = best.get(identity)
            if current is None or (candidate["hops"], -candidate["score"]) < (current["hops"], -current["score"]):
                best[identity] = candidate
    ordered = sorted(best.values(), key=lambda item: (item["hops"], -item["score"], str(item["identity"])))
    return ordered[:max(1, int(max_hits))]
