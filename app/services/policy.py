"""行业政策法规问答服务。

生产环境可以把这里的哈希向量检索替换为 pgvector + Elasticsearch；当前实现保留
相同的召回、引用和降级契约，保证没有外部模型或搜索服务时也不会编造答案。
"""
from __future__ import annotations

import html
import json
import re
import time
from contextvars import ContextVar
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import logging

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..config import settings
from ..models import ComplianceReport, PolicyClause, PolicyDocument, QALog
from ..agent.runtime import agent_run, current_run, snapshot, step, traced
from ..agent.runtime_flags import disabled as flag_disabled
from ..agent.runtime_flags import enabled as flag_enabled
from ..agent.governance import principal_var
from ..agent import ltr as ltr_ranking
from ..agent.retrieval import bm25_scores, reciprocal_rank_fusion, rerank, rewrite_query
from ..agent.roles import AgentPipeline, EvidenceVerifier, FunctionActor, FunctionRetriever, TaskContext, WorkflowPlanner
from . import model_router
from .llm import LLMClient, LLMError
from .materials import (
    EmbeddingError,
    embed_text,
    embed_texts,
    embedding_info,
    embedding_is_compatible,
    parse_material,
    chunk_metadata,
    TextChunk,
    split_text_chunks,
)

DISCLAIMER = "本结果为基于公开信息的初步比对，不构成法律意见；请结合完整材料咨询专业人士。"
AI_DISCLAIMER = "AI 生成，仅供参考，不构成法律意见。"
CURRENT_STATUSES = {"现行有效", "有效"}
ARTICLE_RE = re.compile(r"(?m)(?<!\S)(第[一二三四五六七八九十百千万零〇\d]+条)")
TERM_RE = re.compile(r"[\u4e00-\u9fa5]{2,}|[A-Za-z0-9_.%\-]+")

# 本次检索被运行时开关关掉的组件（G5）。检索与生成在同一请求上下文内执行，
# 因此用 contextvar 把"检索侧降级原因"传给答案组装，避免只在有命中时才看得见。
retrieval_flags_var: ContextVar[list[str]] = ContextVar("policy_retrieval_flags", default=[])
FLAG_LABELS = {
    "kg": "图谱召回",
    "semantic_rerank": "语义精排",
    "remote_llm": "外部生成模型",
    "remote_embedding": "外部向量模型",
    "factcheck": "模型事实核查",
    "ltr": "LTR 学习排序",
}


class PublicSourceFetchError(Exception):
    """公开链接抓取失败，可安全地映射为 API 错误。"""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class _VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if not self.skip_depth and data.strip():
            self.parts.append(data.strip())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in TERM_RE.findall((text or "").lower()):
        terms.append(token)
        if re.fullmatch(r"[\u4e00-\u9fa5]+", token) and len(token) > 2:
            terms.extend(token[index : index + 2] for index in range(len(token) - 1))
    return list(dict.fromkeys(terms))


def _safe_title(filename: str) -> str:
    name = Path(filename).stem.strip()
    return name or "未命名政策文件"


def split_policy_clauses(text: str) -> list[dict]:
    """Identify article boundaries before retrieval chunking."""
    normalized = re.sub(r"\r\n?", "\n", text or "").strip()
    if not normalized:
        return []
    matches = list(ARTICLE_RE.finditer(normalized))
    if not matches:
        return [{"article_no": "", "chapter_path": "", "content": normalized, "page": 0}]

    clauses: list[dict] = []
    prefix = normalized[: matches[0].start()].strip()
    chapter = _last_heading(prefix)
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
        content = normalized[start:end].strip()
        if not content:
            continue
        chapter = _last_heading(normalized[max(0, start - 180) : start]) or chapter
        clauses.append(
            {
                "article_no": match.group(1),
                "chapter_path": chapter,
                "content": content,
                "page": max(1, normalized[:start].count("\f") + 1),
            }
        )
    return clauses or [{"article_no": "", "chapter_path": "", "content": normalized, "page": 0}]


def _refine_policy_clauses(clauses: list[dict]) -> list[dict]:
    """Keep article boundaries, refining only oversized articles into child chunks."""
    semantic_embedder = (
        embed_texts if settings.chunk_semantic_enabled and settings.embedding_api_key and settings.embedding_model
        else None
    )
    refined: list[dict] = []
    for parent_index, clause in enumerate(clauses):
        if clause["article_no"] and len(clause["content"]) <= settings.chunk_semantic_trigger_size:
            parts = [TextChunk(
                clause["content"], 0, "article", 0, len(clause["content"]), clause["content"],
            )]
        else:
            parts = split_text_chunks(
                clause["content"], chunk_size=800, overlap=80,
                semantic=semantic_embedder is not None, embedder=semantic_embedder,
                preserve_parent=bool(clause["article_no"]),
            )
        for index, part in enumerate(parts):
            refined.append(
                {
                    **clause,
                    "content": part.text,
                    "meta": {
                        **chunk_metadata(part),
                        "parent_key": f"article:{parent_index}" if clause["article_no"] else f"block:{part.parent_index}",
                        "parent_article_no": clause["article_no"],
                        "child_index": index,
                    },
                }
            )
    return refined


def _last_heading(text: str) -> str:
    headings = re.findall(r"(?:第[一二三四五六七八九十百千万零〇\d]+章[^\n]{0,80}|[一二三四五六七八九十百千万零〇\d]+、[^\n]{0,80})", text)
    return headings[-1].strip() if headings else ""


def create_policy_document(
    db: Session,
    *,
    title: str,
    content: str,
    doc_number: str = "",
    issuing_authority: str = "",
    level: str = "其他",
    status: str = "现行有效",
    industry_tags: list[str] | None = None,
    source_url: str = "",
    file_path: str = "",
    publish_date: datetime | None = None,
    effective_date: datetime | None = None,
    expiry_date: datetime | None = None,
    region: str = "",
    policy_version: str = "",
) -> PolicyDocument:
    dates = [publish_date, effective_date, expiry_date]
    dates = [item.astimezone(timezone.utc).replace(tzinfo=None) if item and item.tzinfo else item for item in dates]
    publish_date, effective_date, expiry_date = dates
    if effective_date and expiry_date and expiry_date <= effective_date:
        raise ValueError("expiry_date must be after effective_date")
    document = PolicyDocument(
        title=title,
        doc_number=doc_number,
        issuing_authority=issuing_authority,
        level=level,
        status=status,
        industry_tags=industry_tags or [],
        source_url=source_url,
        file_path=file_path,
        text_content=content,
        parse_status="解析中",
        publish_date=publish_date,
        effective_date=effective_date,
        expiry_date=expiry_date,
        region=region,
        policy_version=policy_version,
    )
    db.add(document)
    db.flush()
    clauses = _refine_policy_clauses(split_policy_clauses(content))
    vectors = embed_texts([clause["content"] for clause in clauses])
    for clause, vector in zip(clauses, vectors):
        db.add(
            PolicyClause(
                doc_id=document.id,
                article_no=clause["article_no"],
                chapter_path=clause["chapter_path"],
                content=clause["content"],
                page=clause["page"],
                embedding=vector,
                meta={
                    "source": "公开文件" if source_url else "用户上传",
                    **clause["meta"],
                    **embedding_info(vector),
                },
            )
        )
    document.parse_status = "已完成"
    db.flush()
    sync_policy_document(db, document)
    db.commit()
    db.refresh(document)
    return document


def sync_policy_document(db, document):
    from ..agent.knowledge import KnowledgeStore
    store = KnowledgeStore(db, "public:policy")
    documents = [document]
    if not store.active():
        documents = db.query(PolicyDocument).filter(PolicyDocument.parse_status == "已完成").all()
    row = store.stage([_policy_manifest(db, item) for item in documents])
    if row.changes["added"] or row.changes["updated"]:
        store.publish(row.id)
    else:
        store.discard(row)
    return row


def _policy_manifest(db, document):
    clauses = db.query(PolicyClause).filter_by(doc_id=document.id).order_by(PolicyClause.id).all()
    return {
        "key": f"policy:{document.id}", "classification": "public",
        "metadata": {
            "documentId": document.id, "title": document.title, "status": document.status,
            "docNumber": document.doc_number, "authority": document.issuing_authority,
            "region": document.region, "policyVersion": document.policy_version,
            "level": document.level, "industryTags": document.industry_tags,
            "publishDate": document.publish_date.isoformat() if document.publish_date else None,
            "effectiveDate": document.effective_date.isoformat() if document.effective_date else None,
            "expiryDate": document.expiry_date.isoformat() if document.expiry_date else None,
            "sourceUrl": document.source_url,
        },
        "chunks": [{"id": c.id, "text": c.content, "embedding": c.embedding, "meta": c.meta,
                    "articleNo": c.article_no, "chapterPath": c.chapter_path, "page": c.page} for c in clauses],
    }


def reindex_policy_embeddings(db: Session, document_id: int | None = None, *, rechunk: bool = False) -> dict:
    if rechunk:
        query = db.query(PolicyDocument).filter(PolicyDocument.parse_status == "已完成")
        if document_id is not None:
            query = query.filter(PolicyDocument.id == document_id)
        documents = query.order_by(PolicyDocument.id).all()
        count = 0
        first_vector = None
        for document in documents:
            parts = _refine_policy_clauses(split_policy_clauses(document.text_content))
            vectors = embed_texts([part["content"] for part in parts])
            db.query(PolicyClause).filter_by(doc_id=document.id).delete(synchronize_session="fetch")
            for part, vector in zip(parts, vectors):
                db.add(PolicyClause(
                    doc_id=document.id, article_no=part["article_no"], chapter_path=part["chapter_path"],
                    content=part["content"], page=part["page"], embedding=vector,
                    meta={"source": "公开文件" if document.source_url else "用户上传",
                          **part["meta"], **embedding_info(vector)},
                ))
                if first_vector is None:
                    first_vector = vector
            count += len(parts)
            db.flush()
            db.expire(document, ["clauses"])
            sync_policy_document(db, document)
        db.commit()
        return {"documents": len(documents), "clauses": count, **embedding_info(first_vector)}
    query = db.query(PolicyClause)
    if document_id is not None:
        query = query.filter(PolicyClause.doc_id == document_id)
    clauses = query.order_by(PolicyClause.id).all()
    vectors = embed_texts([clause.content for clause in clauses]) if clauses else []
    document_ids: set[int] = set()
    for clause, vector in zip(clauses, vectors):
        clause.embedding = vector
        clause.meta = {**(clause.meta or {}), **embedding_info(vector)}
        document_ids.add(clause.doc_id)
    db.flush()
    for doc_id in document_ids:
        sync_policy_document(db, db.get(PolicyDocument, doc_id))
    db.commit()
    return {
        "documents": len(document_ids),
        "clauses": len(clauses),
        **embedding_info(vectors[0] if vectors else None),
    }


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    left_norm = sum(v * v for v in left) ** 0.5
    right_norm = sum(v * v for v in right) ** 0.5
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


@traced("retrieval.hybrid", prompt_version="policy-retrieval-v2")
def search_policy_clauses(
    db: Session,
    query: str,
    *,
    industry: str = "",
    level: str = "",
    authority: str = "",
    limit: int = 6,
    region: str = "",
    policy_name: str = "",
    as_of: date | datetime | None = None,
    fusion_sources: tuple[str, ...] | None = None,
) -> list[dict]:
    """条款检索：BM25 + Dense +（可选的）图谱遍历三路 RRF 融合后再精排。

    `fusion_sources` 是评测用的受控开关：`("dense",)` 为纯向量口径，
    `("lexical", "dense")` 是现有主链路，加入 `"graph"` 即"向量 + 图"。
    默认由 `settings.kg_enabled` 决定是否带图，生产上不改调用方行为。
    """
    query = (query or "").strip()
    if not query:
        return []
    rewritten = rewrite_query(query)
    terms = _terms(rewritten)
    at = as_of or _now()
    if not isinstance(at, datetime):
        at = datetime.combine(at, datetime.min.time())
    if at.tzinfo:
        at = at.astimezone(timezone.utc).replace(tzinfo=None)
    with step("retrieval.dense", inputs={"query": rewritten}) as dense_step:
        dense_disabled_reason = ""
        try:
            q_vec = embed_text(rewritten)
            dense_step["output"] = embedding_info(q_vec)
        except EmbeddingError as exc:
            q_vec = []
            dense_disabled_reason = (
                "runtime-flag-remote-embedding-off"
                if (settings.embedding_api_key and settings.embedding_model
                    and flag_disabled("remote_embedding"))
                else "embedding-unavailable"
            )
            dense_step["output"] = {
                "degraded": True, "backend": "unavailable", "reason": dense_disabled_reason,
            }
            logging.getLogger(__name__).warning("向量检索路不可用（%s）: %s", dense_disabled_reason, exc)
    from ..agent.knowledge import KnowledgeStore
    knowledge = KnowledgeStore(db, "public:policy").snapshot()
    rows = _snapshot_clauses(knowledge, at) if knowledge["releaseId"] else (
        db.query(PolicyClause)
        .options(joinedload(PolicyClause.document))
        .join(PolicyDocument)
        .filter(PolicyDocument.status.in_(CURRENT_STATUSES), PolicyDocument.parse_status == "已完成")
        .filter(
            or_(PolicyDocument.publish_date.is_(None), PolicyDocument.publish_date <= at),
            or_(PolicyDocument.effective_date.is_(None), PolicyDocument.effective_date <= at),
            or_(PolicyDocument.expiry_date.is_(None), PolicyDocument.expiry_date > at),
        )
        .all()
    )
    eligible = []
    for clause in rows:
        document = clause.document
        tags = [str(item).lower() for item in (document.industry_tags or [])]
        if industry and industry.lower() not in tags:
            continue
        if level and document.level != level:
            continue
        if authority and authority.lower() not in (document.issuing_authority or "").lower():
            continue
        if region and document.region not in {region, "全国"}:
            continue
        if policy_name and policy_name.lower() not in document.title.lower():
            continue
        eligible.append(clause)
    # Select the latest eligible version, not a future or expired replacement.
    newest = {}
    for clause in eligible:
        document = clause.document
        key = (document.doc_number or document.title, document.issuing_authority, document.region)
        version_key = (document.effective_date or datetime.min, document.publish_date or datetime.min, document.id)
        if key not in newest or version_key > newest[key][0]:
            newest[key] = (version_key, document.id)
    eligible = [clause for clause in eligible if clause.doc_id == newest[
        (clause.document.doc_number or clause.document.title, clause.document.issuing_authority, clause.document.region)
    ][1]]
    texts = [" ".join([clause.document.title, clause.document.doc_number, clause.document.issuing_authority, clause.article_no, clause.content]) for clause in eligible]
    with step("retrieval.bm25", inputs={"query": rewritten, "corpus_size": len(texts)}) as bm25_step:
        lexical_scores = bm25_scores(rewritten, texts)
        bm25_step["output"] = {"backend": "rank-bm25-plus", "delta": 0}
    candidate_limit = max(20, min(limit * 4, 80))
    # 融合来源可注入：评测需要"纯向量"与"向量 + 图"两种受控口径，唯一变量是图这一路。
    sources = tuple(fusion_sources) if fusion_sources else (
        ("lexical", "dense") + (("graph",) if flag_enabled("kg") else ())
    )
    # G5：本次检索被运行时开关关掉的组件要出现在降级说明里，不允许静默关闭。
    disabled_flags: list[str] = []
    if settings.kg_enabled and flag_disabled("kg") and fusion_sources is None:
        disabled_flags.append("kg")
    if dense_disabled_reason == "runtime-flag-remote-embedding-off":
        disabled_flags.append("remote_embedding")
    retrieval_flags_var.set(disabled_flags)
    use_lexical, use_dense = "lexical" in sources, "dense" in sources
    dense_floor = 0.25 if settings.embedding_api_key else 0.35
    from ..kg.retrieval import clause_identities, rank_clause_indices

    graph_hits: list[dict] = []
    graph_info: dict = {"enabled": "graph" in sources, "sources": list(sources)}
    if "graph" in sources:
        from ..kg.retrieval import graph_search
        with step("retrieval.graph", inputs={"query": rewritten}) as graph_step:
            try:
                graph_result = graph_search(db, rewritten, limit=settings.kg_clause_limit)
                graph_hits = list(graph_result.get("hits") or [])
                diagnostics = graph_result.get("graph") or {}
                graph_info.update({
                    "degraded": False,
                    "seeds": [seed.get("name") for seed in graph_result.get("seeds") or []][:8],
                    "hits": len(graph_hits),
                    "graphNodes": diagnostics.get("nodes"),
                    "graphRelations": diagnostics.get("relations"),
                    "truncated": bool(diagnostics.get("truncated")),
                    "communities": [item.get("id") for item in graph_result.get("communities") or []],
                    "paths": [{
                        "articleNo": hit.get("articleNo"), "hops": hit.get("hops"),
                        "relevance": hit.get("relevance"),
                        "steps": [
                            f"{item.get('label')}:{item.get('from')}->{item.get('to')}"
                            for item in hit.get("path") or []
                        ],
                    } for hit in graph_hits[:5]],
                })
                graph_step["output"] = {
                    key: graph_info[key] for key in ("hits", "seeds", "graphNodes", "graphRelations")
                }
            except Exception as exc:  # noqa: BLE001  图谱是加速项，异常不得拖垮主链路
                logging.getLogger(__name__).warning("图谱召回降级: %s", exc)
                graph_hits = []
                graph_info.update({"degraded": True, "error": type(exc).__name__})
                graph_step["output"] = {"degraded": True, "error": type(exc).__name__}
    graph_index: dict = {}
    for hit in graph_hits:
        graph_index.setdefault(hit.get("identity"), hit)

    ranked: list[dict] = []
    for clause, lexical, haystack in zip(eligible, lexical_scores, texts):
        document = clause.document
        haystack = haystack.lower()
        keyword_hits = sum(1 for term in terms if term in haystack)
        title_hits = sum(1 for term in terms if term in (document.title or "").lower())
        cosine = (
            _cosine(q_vec, clause.embedding or [])
            if embedding_is_compatible(clause.meta, q_vec)
            else 0.0
        )
        graph_hit = next(
            (graph_index[identity] for identity in clause_identities(clause) if identity in graph_index),
            None,
        )
        # 图路命中不受词面/向量门槛限制：把"关系可达但词面不可达"的条款补进候选，
        # 否则图只能给已有候选重排，Recall 上不可能有增益。
        if graph_hit is None and not (
            (use_lexical and lexical > 0) or (use_dense and cosine >= dense_floor)
        ):
            continue
        ranked.append(
            {
                "clause": clause,
                "document": document,
                "bm25_score": lexical,
                "dense_score": cosine,
                "keyword_hits": keyword_hits,
                "graph_hit": graph_hit is not None,
                "graph_hops": (graph_hit or {}).get("hops"),
                "graph_relevance": (graph_hit or {}).get("relevance"),
            }
        )
    lexical_order = sorted(
        [index for index, row in enumerate(ranked) if row["bm25_score"] > 0],
        key=lambda index: ranked[index]["bm25_score"], reverse=True,
    )[:candidate_limit] if use_lexical else []
    dense_order = sorted(
        [index for index, row in enumerate(ranked) if row["dense_score"] >= dense_floor],
        key=lambda index: ranked[index]["dense_score"], reverse=True,
    )[:candidate_limit] if use_dense else []
    rankings = [order for order in (lexical_order, dense_order) if order]
    if "graph" in sources:
        graph_order = rank_clause_indices(graph_hits, [row["clause"] for row in ranked])
        if graph_order:
            rankings.append(graph_order)
        graph_info.update({"matched": len(graph_order), "candidates": len(ranked)})
    if not rankings:
        rankings = [list(range(len(ranked)))]
    fusion = reciprocal_rank_fusion(rankings)
    for index, score in fusion.items():
        ranked[index]["rrf_score"] = score
    # G9：RRF 先给出保底顺序与完整候选池，LTR 只在池内重排（会改变谁进 candidate_limit），
    # 模型缺失 / 任何异常都退回 RRF 顺序并标记 degraded，绝不让检索失败或返回空。
    pool = [ranked[index] for index in sorted(fusion, key=fusion.get, reverse=True)]
    ltr_mode, ltr_reason = ltr_ranking.active_mode()
    ltr_info = {
        "mode": ltr_ranking.MODE_OFF, "alpha": float(settings.ltr_blend_alpha),
        "model": None, "modelVersion": "", "shadowTopChanged": 0, "degraded": False, "reason": "",
    }
    if ltr_mode != ltr_ranking.MODE_OFF:
        with step("retrieval.ltr", inputs={"query": rewritten, "mode": ltr_mode, "pool": len(pool)}) as ltr_step:
            active_model = ltr_ranking.load_active(db, domain="policy", tenant_id="")
            pool, ltr_info = ltr_ranking.rank(
                pool, mode=ltr_mode, model=active_model, alpha=settings.ltr_blend_alpha,
            )
            ltr_step["output"] = {
                "mode": ltr_info["mode"], "model": ltr_info.get("modelVersion"),
                "alpha": ltr_info["alpha"], "shadowTopChanged": ltr_info["shadowTopChanged"],
                "degraded": ltr_info["degraded"], "reason": ltr_info["reason"],
            }
    elif ltr_reason:
        # 配置里启用了 LTR 但被运行时开关显式关闭：必须标记降级，不允许静默。
        ltr_info.update(degraded=True, reason=ltr_reason)
    if ltr_info.get("reason") == "runtime-flag-ltr-off" and "ltr" not in disabled_flags:
        disabled_flags.append("ltr")
        retrieval_flags_var.set(disabled_flags)
    candidates = pool[:candidate_limit]
    ranked, rerank_info = rerank(query, candidates)
    result = []
    parents = set()
    for row in ranked:
        clause = row["clause"]
        key = (clause.doc_id, (clause.meta or {}).get("parent_key", clause.id))
        if key in parents:
            continue
        parents.add(key)
        result.append(row)
        if len(result) >= max(1, min(limit, 20)):
            break
    # G7 检索末条 filter：结果出站前按角色 / 租户 / 密级 / 部门 / 属主再复核一次。
    # public:policy 域基本都是 public 数据，这一道通常零拒绝；它的作用是：政策域一旦出现受限条目，
    # 或身份与租户不匹配，也不让条目绕过既有防线进入答案。
    from ..agent.access import access_diagnostics, filter_visible
    principal = principal_var.get()
    result, rejected = filter_visible(
        result, principal,
        level_of=lambda row: (row["clause"].meta or {}).get("classification") or "public",
        tenant_of=lambda row: (row["clause"].meta or {}).get("tenant_id", ""),
        department_of=lambda row: (row["clause"].meta or {}).get("department_id", ""),
        owner_of=lambda row: (row["clause"].meta or {}).get("owner_id", ""),
    )
    access_info = access_diagnostics(principal, filtered=rejected)
    for row in result:
        row["retrieval"] = {
            "rewrittenQuery": rewritten, "asOf": at.isoformat(),
            "bm25": row["bm25_score"], "dense": row["dense_score"], "rrf": row["rrf_score"],
            "rerank": row["rerank_score"], "reranker": rerank_info,
            "fusionSources": list(sources), "graph": graph_info,
            "graphHit": bool(row.get("graph_hit")), "graphHops": row.get("graph_hops"),
            "graphRelevance": row.get("graph_relevance"),
            "denseBackend": (
                "disabled-by-flag" if dense_disabled_reason == "runtime-flag-remote-embedding-off"
                else "api" if settings.embedding_api_key and q_vec
                else "offline-hash" if q_vec else "unavailable"
            ),
            "denseDisabled": bool(dense_disabled_reason),
            "denseDisabledReason": dense_disabled_reason,
            "runtimeFlags": list(disabled_flags),
            "knowledgeVersion": knowledge["version"], "knowledgeReleaseId": knowledge["releaseId"],
            "access": access_info,
            "ltr": ltr_info,
            # 行级 LTR 分只用于核对与评测：blend 模式下排序依据，shadow 模式下仅供影子对比。
            "ltrScore": row.get("ltr_score"),
            "ltrFeatures": row.get("ltr_features"),
            "blendScore": row.get("blend_score"),
        }
    with step("retrieval.evidence") as evidence_step:
        evidence_step["evidence"] = [
            {"clause_id": row["clause"].id, "doc_id": row["document"].id, **row["retrieval"]}
            for row in result
        ]
    return result


def _snapshot_clauses(knowledge, at):
    """Read content, metadata and vectors from the same immutable release."""
    rows = []
    for entry in knowledge["entries"]:
        metadata = entry["metadata_"]
        def parse_date(name):
            value = metadata.get(name)
            return datetime.fromisoformat(value).replace(tzinfo=None) if value else None
        publish, effective, expiry = (parse_date(k) for k in ("publishDate", "effectiveDate", "expiryDate"))
        if metadata.get("status", "现行有效") not in CURRENT_STATUSES:
            continue
        if (publish and publish > at) or (effective and effective > at) or (expiry and expiry <= at):
            continue
        # Stable negative IDs keep API citations compatible for API-authored documents.
        document_id = metadata.get("documentId") or -int(entry["content_hash"][:12], 16)
        document = SimpleNamespace(
            id=document_id, title=metadata.get("title", entry["key"]), doc_number=metadata.get("docNumber", ""),
            issuing_authority=metadata.get("authority", ""), region=metadata.get("region", ""),
            policy_version=metadata.get("policyVersion", ""), level=metadata.get("level", "其他"),
            industry_tags=metadata.get("industryTags", []), status=metadata.get("status", "现行有效"),
            source_url=metadata.get("sourceUrl", ""), publish_date=publish, effective_date=effective, expiry_date=expiry,
        )
        for index, chunk in enumerate(entry["chunks"]):
            rows.append(SimpleNamespace(
                id=chunk.get("id") or -(abs(document_id) * 10000 + index + 1),
                doc_id=document_id, document=document, content=chunk["text"],
                embedding=chunk.get("embedding", []), meta=chunk.get("meta", {}),
                article_no=chunk.get("articleNo", ""), chapter_path=chunk.get("chapterPath", ""),
                page=chunk.get("page", 0),
            ))
    return rows


def citation_for(row: dict | PolicyClause) -> dict:
    if isinstance(row, dict):
        clause = row["clause"]
        document = row["document"]
    else:
        clause = row
        document = row.document
    return {
        "id": clause.id,
        "docTitle": document.title,
        "articleNo": clause.article_no,
        "excerpt": (clause.meta or {}).get("parent_text") or clause.content[:1200],
        "sourceUrl": document.source_url,
        "page": clause.page or 0,
        "status": document.status,
        "documentId": document.id,
        "chapterPath": clause.chapter_path,
        "effectiveDate": document.effective_date.isoformat() if document.effective_date else None,
        "expiryDate": document.expiry_date.isoformat() if document.expiry_date else None,
        "region": document.region,
        "policyVersion": document.policy_version,
        "knowledgeVersion": row.get("retrieval", {}).get("knowledgeVersion") if isinstance(row, dict) else None,
        "knowledgeReleaseId": row.get("retrieval", {}).get("knowledgeReleaseId") if isinstance(row, dict) else None,
    }


def _intent(question: str) -> str:
    if any(word in question for word in ("合规", "是否符合", "风险", "比对", "要求我司")):
        return "比对"
    if any(word in question for word in ("解读", "什么意思", "怎么理解", "白话")):
        return "解读"
    return "检索"


def _fallback_answer(citations: list[dict]) -> str:
    if not citations:
        return "未检索到现行有效且有明确出处的相关政策条款，暂不生成结论。请补充行业、地区、法规名称或上传公开文件后重试。"
    lines = ["检索到以下相关政策条款，建议以原文和最新发布版本为准："]
    for index, citation in enumerate(citations, 1):
        label = f"《{citation['docTitle']}》{citation['articleNo']}".strip()
        lines.append(f"[引用{index}] {label}：{citation['excerpt'][:260]}")
    return "\n".join(lines)


def _llm_answer(question: str, citations: list[dict], llm: LLMClient) -> tuple[str, list[str]]:
    if llm.is_mock or not citations:
        return _fallback_answer(citations), []
    context = "\n\n".join(
        f"[{index}] {item['docTitle']} {item['articleNo']}\n{item['excerpt']}"
        for index, item in enumerate(citations, 1)
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是政策法规检索助手。只能基于用户提供的条款回答，不能补充常识或外推。"
                "每一个可验证结论必须带 [引用N]，条款没有明确规定时必须说未检索到明确规定。"
                '只输出 JSON：{"answer":"...","usedCitations":[1,2]}。'
            ),
        },
        {"role": "user", "content": f"问题：{question}\n\n条款：\n{context}"},
    ]
    capture = current_run.get()
    if capture and capture.memory:
        messages.insert(1, {
            "role": "system",
            "content": "会话记忆仅用于理解指代和行文偏好，不是政策事实来源；只能引用本轮检索到的条款。",
        })
        messages[-1]["content"] += "\n\n辅助会话上下文：\n" + json.dumps(
            snapshot(capture.memory), ensure_ascii=False,
        )[:12000]
    try:
        data = llm.chat_json(
            # G4：走分层路由。判定文本必须是"用户问句"而不是拼上条款后的完整 prompt，
            # 否则条款越长分数越高，提问的复杂度差异会被上下文长度淹没。
            messages, temperature=0, purpose="policy.answer", routing_text=question,
            citation_count=len(citations), context_chars=len(context),
        )
        answer = str(data.get("answer") or "").strip()
        used = [int(index) for index in data.get("usedCitations", []) if str(index).isdigit()]
        references = {int(index) for index in re.findall(r"\[引用(\d+)\]", answer)}
        if answer and used and references == set(used) and all(1 <= index <= len(citations) for index in used):
            return answer, []
    except (LLMError, ValueError, TypeError) as exc:
        return _fallback_answer(citations), [f"模型生成失败，已降级为检索结果：{exc}"]
    return _fallback_answer(citations), ["模型未返回可验证引用，已降级为检索结果。"]


@agent_run("policy_qa", plan=("query_rewrite", "bm25", "dense", "filter", "rerank", "answer", "verify"))
def answer_policy(db: Session, request, llm: LLMClient | None = None) -> dict:
    started = time.perf_counter()
    llm = llm or LLMClient()
    pipeline = AgentPipeline(
        WorkflowPlanner(permission="policy:read", required_fields=("question",)),
        FunctionRetriever(lambda context: search_policy_clauses(
            db, request.question, industry=request.industry, level=request.level,
            authority=request.authority, limit=request.limit,
            region=getattr(request, "region", ""), policy_name=getattr(request, "policyName", ""),
            as_of=getattr(request, "asOf", None),
        )),
        FunctionActor(lambda context, hits: _policy_result(request, llm, hits)),
        EvidenceVerifier(lambda context, hits, result: {
            "passed": not hits or all(item["id"] in {hit["clause"].id for hit in hits} for item in result["clauses"]),
            "citation_ids": [item["id"] for item in result["clauses"]],
            "has_evidence": bool(hits), "risk_flags": result["riskFlags"],
            "refused": not bool(hits),
        }),
    )
    response = pipeline.execute(TaskContext(
        "policy_qa", request.model_dump(mode="json"), memory=current_run.get().memory,
    ))
    capture = current_run.get()
    principal = principal_var.get()
    db.add(QALog(
        session_id=request.sessionId or "", question=request.question, answer=response["answer"],
        citations=response["clauses"], model=response["model"],
        latency_ms=int((time.perf_counter() - started) * 1000),
        tenant_id=principal.tenant_id or "default", user_id=principal.user_id,
        run_id=capture.run_id if capture else "",
    ))
    db.commit()
    return response


def runtime_degradation_reasons(hits: list[dict]) -> list[str]:
    """把 G5 运行时开关造成的检索侧降级翻译成答案侧说明：不隐藏、不估算、不重复。"""
    reasons: list[str] = []
    covered: set[str] = set()
    if hits:
        first = hits[0].get("retrieval") or {}
        if first.get("denseDisabled"):
            flag_off = first.get("denseDisabledReason") == "runtime-flag-remote-embedding-off"
            detail = "运行时开关关闭" if flag_off else "向量服务不可用"
            reasons.append(f"向量检索路已停用（{detail}），本次仅用关键词与图谱信号排序")
            if flag_off:
                covered.add("remote_embedding")
        if flag_disabled("kg") and "graph" not in (first.get("fusionSources") or []):
            reasons.append("图谱召回已被运行时开关关闭")
            covered.add("kg")
        reranker = first.get("reranker") or {}
        if reranker.get("reason") == "runtime-flag-semantic-rerank-off":
            reasons.append("语义精排已被运行时开关关闭，改用确定性词法重排")
            covered.add("semantic_rerank")
        elif reranker.get("reason") == "rerank-pool-saturated":
            reasons.append("精排容量池已满，已快速失败并改用确定性词法重排")
        ltr_info = first.get("ltr") or {}
        if ltr_info.get("degraded") and ltr_info.get("reason") == "no-active-model":
            reasons.append("LTR 排序已启用但没有激活模型，本次已退回 RRF 保底顺序")
            covered.add("ltr")
    for name in retrieval_flags_var.get():
        if name in covered:
            continue
        text = f"运行时开关关闭：{FLAG_LABELS.get(name, name)}"
        if text not in reasons:
            reasons.append(text)
    return reasons


def _routed_model(purpose: str, llm, offline_label: str) -> str:
    """响应体里的模型名必须与实际调用一致，不能固定写配置默认值。

    路由关闭或未配置分层模型时，`last_decision()` 仍会给出标准层模型（等于配置默认值），
    因此这里不会改变未启用路由时的对外字段。
    """
    if llm.is_mock:
        return offline_label
    decision = model_router.last_decision(purpose) or {}
    return decision.get("model") or settings.llm_model_generation


def _policy_result(request, llm, hits):
    citations = [citation_for(hit) for hit in hits]
    with step("policy.answer", model=settings.llm_model_generation if not llm.is_mock else "offline", prompt_version="policy-answer-v2") as answer_step:
        answer, risk_flags = _llm_answer(request.question, citations, llm)
        decision = model_router.last_decision("policy.answer") or {}
        if decision.get("model"):
            answer_step["model"] = decision["model"]
        answer_step["output"] = answer
        answer_step["evidence"] = [citation["id"] for citation in citations]
    if hits and any(not row["document"].effective_date for row in hits):
        risk_flags.append("部分政策缺少生效日期，时效需人工核实")
    if hits and hits[0]["retrieval"]["reranker"]["backend"] == "deterministic-lexical":
        risk_flags.append("未使用语义重排模型，已采用确定性重排")
    if not hits:
        risk_flags = [*risk_flags, "未检索到相关现行有效条款"]
    confidence = "high" if hits and hits[0]["keyword_hits"] >= 2 else ("medium" if hits else "none")
    # 兜底口径（G2 体验层）：答案是否由模型基于检索条款生成，而非检索摘要/降级话术。
    degradation_reasons = []
    if not hits:
        degradation_reasons.append("未检索到现行有效条款")
    if llm.is_mock:
        if flag_disabled("remote_llm"):
            degradation_reasons.append("运行时开关已关闭外部生成模型，答案由检索结果兜底")
        else:
            degradation_reasons.append("未配置生成模型，答案由检索结果兜底")
    degradation_reasons.extend(flag for flag in risk_flags if "降级" in flag)
    # G5：检索侧被运行时开关关掉的组件必须显式出现在降级说明里（含无命中时）。
    degradation_reasons.extend(runtime_degradation_reasons(hits))
    response = {
        "answer": answer,
        "clauses": citations,
        "sources": citations,
        "confidence": confidence,
        "generatedAt": _now(),
        "model": _routed_model("policy.answer", llm, "offline-policy-retrieval"),
        "routing": decision or None,
        "riskFlags": risk_flags,
        "intent": _intent(request.question),
        "queryTerms": _terms(request.question),
        "retrieval": [row["retrieval"] for row in hits],
        "degraded": bool(degradation_reasons),
        "degradationReasons": degradation_reasons,
    }
    return response


def _interpret_fallback(text: str) -> dict:
    clean = re.sub(r"^第[^条]{1,20}条", "", text).strip(" ：:，,。")
    obligations = [clean[:180]] if any(word in clean for word in ("应当", "必须", "需", "应在")) else []
    prohibitions = [clean[:180]] if any(word in clean for word in ("不得", "禁止", "严禁")) else []
    consequences = [part.strip() for part in re.split(r"[。；]", clean) if any(word in part for word in ("处罚", "罚款", "责任", "追究"))]
    return {
        "plainSummary": f"这段条文主要规定：{clean[:260]}",
        "applicableObjects": ["需要结合条文上下文和配套文件进一步确认"],
        "obligations": obligations or ["条文未能直接识别出明确义务，请核对完整原文"],
        "prohibitions": prohibitions,
        "consequences": consequences,
    }


def _interpret_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


@agent_run("policy_interpretation")
@traced("policy.interpret", prompt_version="policy-interpret-v1")
def interpret_clause(db: Session, request, llm: LLMClient | None = None) -> dict:
    llm = llm or LLMClient()
    from ..agent.knowledge import KnowledgeStore
    knowledge = KnowledgeStore(db, "public:policy").snapshot()
    snapshot_rows = _snapshot_clauses(knowledge, _now().replace(tzinfo=None)) if knowledge["releaseId"] else []
    clause = (next((r for r in snapshot_rows if r.id == request.clauseId), None)
              if knowledge["releaseId"] else db.get(PolicyClause, request.clauseId)) if request.clauseId else None
    if request.clauseId and not clause:
        raise ValueError("条款不在当前有效知识库版本中，请重新检索")
    text = ((clause.meta or {}).get("parent_text") or clause.content) if clause else (request.clauseText or "").strip()
    if not text:
        raise ValueError("clauseId 或 clauseText 至少提供一项")
    base_citation = citation_for(clause) if clause else {
        "id": None,
        "docTitle": request.docTitle or "用户提供条文",
        "articleNo": request.articleNo,
        "excerpt": text[:1200],
        "sourceUrl": request.sourceUrl,
        "page": 0,
        "status": "待核实",
    }
    result = _interpret_fallback(text)
    risk_flags: list[str] = []
    if not clause:
        risk_flags.append("用户提供的条文未绑定知识库出处")
    if not llm.is_mock:
        messages = [
            {"role": "system", "content": "你是政策条款解读助手，只能解释给定原文，不得添加原文没有的法律结论。只输出 JSON，字段为 plainSummary、applicableObjects、obligations、prohibitions、consequences。"},
            {"role": "user", "content": text},
        ]
        try:
            candidate = llm.chat_json(messages, temperature=0, purpose="policy.interpret")
            plain_summary = candidate.get("plainSummary")
            if isinstance(plain_summary, str) and plain_summary.strip():
                result["plainSummary"] = plain_summary.strip()
            for key in ("applicableObjects", "obligations", "prohibitions", "consequences"):
                items = _interpret_list(candidate.get(key))
                if items:
                    result[key] = items
        except (LLMError, ValueError, TypeError) as exc:
            risk_flags.append(f"模型解读失败，已使用规则化摘要：{exc}")
    related = []
    if clause:
        related_rows = ([r for r in snapshot_rows if r.doc_id == clause.doc_id and r.id != clause.id]
                        if knowledge["releaseId"] else (
            db.query(PolicyClause)
            .filter(PolicyClause.doc_id == clause.doc_id, PolicyClause.id != clause.id)
            .order_by(PolicyClause.id)
            .all()
        ))
        parents = {(clause.meta or {}).get("parent_key", clause.id)}
        for item in related_rows:
            parent_key = (item.meta or {}).get("parent_key", item.id)
            if parent_key in parents:
                continue
            parents.add(parent_key)
            item.document = clause.document
            related.append(citation_for(item))
            if len(related) >= 3:
                break
    return {
        **result,
        "relatedClauses": related,
        "citations": [base_citation],
        "disclaimer": AI_DISCLAIMER,
        "generatedAt": _now(),
        "model": _routed_model("policy.interpret", llm, "offline-policy-interpretation"),
        "routing": model_router.last_decision("policy.interpret"),
        "riskFlags": risk_flags,
    }


@agent_run("compliance")
@traced("policy.compliance", prompt_version="compliance-v1")
def check_compliance(db: Session, request, llm: LLMClient | None = None) -> dict:
    llm = llm or LLMClient()
    hits = search_policy_clauses(db, request.businessDesc, industry=request.industry, limit=request.limit)
    items = []
    for hit in hits:
        citation = citation_for(hit)
        items.append(
            {
                "requirement": citation["excerpt"],
                "citation": citation,
                "enterpriseMatch": "仅凭当前公开业务描述无法确认是否满足，需人工核实完整材料。",
                "riskLevel": "待人工核实",
                "suggestion": "核对该条款适用范围、资质证照、流程记录及最新配套规定，并保留核验凭证。",
            }
        )
    risk_flags = [] if hits else ["未检索到可用于比对的现行有效条款"]
    model = settings.llm_model_generation if not llm.is_mock else "offline-compliance-screening"
    response = {
        "items": items,
        "disclaimer": DISCLAIMER,
        "generatedAt": _now(),
        "model": model,
        "riskFlags": risk_flags,
    }
    db.add(
        ComplianceReport(
            business_desc=request.businessDesc,
            industry=request.industry,
            items=items,
            model=model,
        )
    )
    db.commit()
    return response


def document_out(document: PolicyDocument) -> dict:
    return {
        "id": document.id,
        "title": document.title,
        "doc_number": document.doc_number,
        "issuing_authority": document.issuing_authority,
        "level": document.level,
        "publish_date": document.publish_date,
        "effective_date": document.effective_date,
        "expiry_date": document.expiry_date,
        "region": document.region,
        "policy_version": document.policy_version,
        "status": document.status,
        "industry_tags": document.industry_tags or [],
        "source_url": document.source_url,
        "file_path": document.file_path,
        "parse_status": document.parse_status,
        "clause_count": len(document.clauses),
        "created_at": document.created_at,
    }


def fetch_public_source(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("仅支持 http/https 公开链接")
    try:
        with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "EAOS-PolicyBot/0.1"}) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 403:
            raise PublicSourceFetchError(
                403,
                "目标网站禁止程序化采集，请下载政策文件后通过“上传政策文件”入库。",
            ) from exc
        raise PublicSourceFetchError(
            502,
            f"目标网站返回 HTTP {exc.response.status_code}，暂时无法采集。",
        ) from exc
    except httpx.TimeoutException as exc:
        raise PublicSourceFetchError(504, "目标网站响应超时，请稍后重试或下载文件后上传。") from exc
    except httpx.HTTPError as exc:
        raise PublicSourceFetchError(502, "无法连接目标网站，请检查链接或稍后重试。") from exc
    content_type = response.headers.get("content-type", "").lower()
    if "html" in content_type or response.text.lstrip().startswith("<"):
        parser = _VisibleTextParser()
        parser.feed(response.text)
        text = "\n".join(parser.parts)
    else:
        text = response.text
    text = html.unescape(re.sub(r"\n{3,}", "\n\n", text)).strip()
    if len(text) < 20:
        raise ValueError("公开链接未提取到足够正文，请改为上传 PDF/Word/TXT 文件")
    return text


def policy_document_by_id(db: Session, document_id: int) -> PolicyDocument | None:
    return (
        db.query(PolicyDocument)
        .options(joinedload(PolicyDocument.clauses))
        .filter(PolicyDocument.id == document_id)
        .first()
    )
