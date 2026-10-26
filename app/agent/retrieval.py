from __future__ import annotations

import math
import re
from functools import lru_cache

import httpx
from rank_bm25 import BM25Plus

from ..config import settings
from ..services import capacity, cost
from .runtime import step
from .runtime_flags import disabled as flag_disabled

TOKEN_RE = re.compile(r"[\u4e00-\u9fa5]+|[A-Za-z0-9_.%\-]+")
QUERY_SYNONYMS = {
    "怎么申请": "申报条件 申请流程 材料",
    "要准备什么": "材料清单",
    "多久": "时限 工作日",
    "什么时候生效": "施行 生效",
    "研发投入": "研发费用",
}


def tokens(text: str) -> list[str]:
    result = []
    for token in TOKEN_RE.findall((text or "").lower()):
        result.append(token)
        if re.fullmatch(r"[\u4e00-\u9fa5]+", token) and len(token) > 2:
            result.extend(token[index:index + 2] for index in range(len(token) - 1))
    return result


def rewrite_query(query: str) -> str:
    additions = [value for key, value in QUERY_SYNONYMS.items() if key in query]
    return " ".join([query.strip(), *additions]).strip()


def bm25_scores(query: str, texts: list[str]) -> list[float]:
    if not texts:
        return []
    corpus = [tokens(text) or ["__empty__"] for text in texts]
    return [float(score) for score in BM25Plus(corpus, delta=0).get_scores(tokens(query))]


def reciprocal_rank_fusion(rankings: list[list[int]], k=60) -> dict[int, float]:
    result = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            result[item] = result.get(item, 0) + 1 / (k + rank)
    return result


@lru_cache(maxsize=1)
def local_reranker(model: str):
    from sentence_transformers import CrossEncoder
    return CrossEncoder(model)


def _local_rerank_scores(model: str, query: str, texts: list[str]) -> list[float]:
    return list(local_reranker(model).predict([(query, text) for text in texts]))


def _remote_rerank_scores(query: str, texts: list[str]) -> list[float]:
    from .governance import model_messages
    api_key = settings.effective_rerank_api_key
    if not api_key:
        raise ValueError("Reranker requires a key or a same-origin embedding key")
    outbound = model_messages({"query": query, "documents": texts})
    response = httpx.post(
        settings.rerank_url,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": settings.rerank_model, **outbound, "top_n": len(texts)},
        timeout=settings.rerank_timeout,
    )
    response.raise_for_status()
    results = response.json()["results"]
    by_index = {int(item["index"]): float(item["relevance_score"]) for item in results}
    if len(results) != len(texts) or set(by_index) != set(range(len(texts))):
        raise ValueError("Reranker omitted or duplicated candidates")
    return [by_index[index] for index in range(len(texts))]


def _ranking_basis(row: dict) -> float:
    """排序基准分：LTR blend 生效时用它，否则回落到 RRF；非有限值一律回落（保底不放松）。"""
    basis = row.get("blend_score")
    if basis is not None:
        try:
            if math.isfinite(float(basis)):
                return float(basis)
        except (TypeError, ValueError):
            pass
    return float(row.get("rrf_score") or 0.0)


def rerank(query: str, candidates: list[dict]) -> tuple[list[dict], dict]:
    with step("retrieval.rerank", inputs={"query": query, "candidate_ids": [row["clause"].id for row in candidates]}) as audit:
        diagnostics = {"backend": "deterministic-lexical", "degraded": False}
        texts = [f"{row['document'].title}\n{row['clause'].content}" for row in candidates]
        scores = None
        # 只有"配置了语义精排 + 运维显式关闭开关"才算运行时降级；
        # 未配置精排属于既有离线口径，不能算降级（否则会改掉离线基线）。
        rerank_configured = bool(settings.rerank_local_model or settings.rerank_url)
        semantic_disabled = rerank_configured and flag_disabled("semantic_rerank")
        if semantic_disabled:
            diagnostics.update(degraded=True, reason="runtime-flag-semantic-rerank-off")
        else:
            try:
                if candidates and settings.rerank_local_model:
                    scores = _local_rerank_scores(settings.rerank_local_model, query, texts)
                    diagnostics["backend"] = "cross-encoder-local"
                elif candidates and settings.rerank_url:
                    # 精排是外部耗时链路：容量池满即快速失败并降级，不拖垮检索链路。
                    scores = capacity.run("rerank", _remote_rerank_scores, query, texts)
                    diagnostics["backend"] = "cross-encoder-api"
                    # G6：远端精排按文档计费、不回 token usage：只记调用次数，成本记 null
                    cost.record_usage(
                        model=settings.rerank_model, purpose="rerank.policy", tokens_available=False,
                    )
                if scores is not None and (len(scores) != len(candidates) or not all(math.isfinite(float(score)) for score in scores)):
                    raise ValueError("Invalid reranker scores")
            except capacity.CapacityError as exc:
                diagnostics.update(degraded=True, reason="rerank-pool-saturated", error="CapacityError")
                scores = None
            except (httpx.HTTPError, KeyError, TypeError, ValueError, ImportError, OSError) as exc:
                diagnostics.update(degraded=True, error=type(exc).__name__)
                scores = None
        if scores is None:
            query_tokens = set(tokens(query))
            scores = []
            for row, text in zip(candidates, texts):
                overlap = len(query_tokens & set(tokens(text))) / max(1, len(query_tokens))
                # G9：词法降级口径下用 LTR 混合分（若开启）替代 RRF 分参与打分，
                # 否则"渐进替换 RRF"会被精排降级路径整段抹掉。
                scores.append(overlap + _ranking_basis(row))
        for row, score in zip(candidates, scores):
            row["rerank_score"] = float(score)
            row["score"] = round(float(score), 6)
        ranked = sorted(candidates, key=lambda row: (-row["rerank_score"], -_ranking_basis(row), row["clause"].id))
        audit["output"] = diagnostics
        audit["evidence"] = [{"clause_id": row["clause"].id, "score": row["score"]} for row in ranked]
        return ranked, diagnostics
