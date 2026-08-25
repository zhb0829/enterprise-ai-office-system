"""历史案例 RAG 与应对建议生成。

Python 独占向量索引（opinion_case_chunk）。案例正文经 Java 权威接口获取。
生成结果必须引用检索到的案例片段；引用不存在或证据不足时禁止确定性结论。
"""
from __future__ import annotations

import json
import logging
import math
import re
import time

from ..db import SessionLocal
from ..config import settings
from ..services.llm import LLMClient, LLMError
from ..services.materials import embed_texts
from .java_client import java_client
from .models_ai import OpinionCaseChunk

logger = logging.getLogger(__name__)

PROMPT_VERSION = "opinion-suggestion-v1"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120
TOP_K = 3


def _chunk(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def reindex_cases() -> dict:
    """从 Java 拉取全部历史案例，重建向量索引（幂等）。"""
    payload = java_client._get("/internal/opinion/cases/all")
    cases = (payload or {}).get("cases") or []
    db = SessionLocal()
    try:
        db.query(OpinionCaseChunk).delete()
        for case in cases:
            source_text = "\n".join(filter(None, [
                f"策略：{case.get('strategy', '')}",
                f"处置：{case.get('content', '')}",
                f"效果：{case.get('effect', '')}",
            ]))
            chunks = _chunk(source_text)
            for index, chunk in enumerate(chunks):
                db.add(OpinionCaseChunk(
                    case_id=int(case.get("id") or 0),
                    case_title=str(case.get("title") or ""),
                    event_type=str(case.get("eventType") or ""),
                    risk_level=str(case.get("riskLevel") or ""),
                    chunk_index=index,
                    text=chunk,
                ))
        db.commit()
        rows = db.query(OpinionCaseChunk).order_by(OpinionCaseChunk.id).all()
        texts = [row.text for row in rows]
        vectors = embed_texts(texts) if texts else []
        for row, vector in zip(rows, vectors):
            row.embedding = vector
            row.meta = {"embedding_backend": "hash-fallback" if _is_hash(vector) else "api"}
        db.commit()
        return {"cases": len(cases), "chunks": len(rows)}
    except Exception as exc:  # noqa: BLE001
        logger.error("案例 RAG 重建失败: %s", exc)
        raise
    finally:
        db.close()


def _is_hash(vector: list[float]) -> bool:
    return all(v in (0.0, 1.0) for v in vector[:8]) if vector else True


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    denom = math.sqrt(sum(v * v for v in left)) * math.sqrt(sum(v * v for v in right))
    if not denom:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / denom


def _retrieve(query: str, limit: int = TOP_K) -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(OpinionCaseChunk).order_by(OpinionCaseChunk.id).all()
        if not rows:
            return []
        query_vec = embed_texts([query])[0]
        query_terms = set(re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z0-9_.%-]+", (query or "").lower()))
        ranked = []
        for row in rows:
            text_lower = (row.text or "").lower()
            keyword_hits = sum(1 for term in query_terms if term and term in text_lower)
            cosine = _cosine(query_vec, row.embedding or [])
            score = keyword_hits * 1.5 + cosine
            if score <= 0:
                continue
            ranked.append({
                "case_id": row.case_id,
                "case_title": row.case_title,
                "text": row.text[:400],
                "score": round(float(score), 4),
            })
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:limit]
    finally:
        db.close()


def generate_suggestion(context: dict) -> dict:
    """基于历史案例生成应对建议。证据不足时返回低可信结论。"""
    query = _query_text(context)
    hits = _retrieve(query)
    model = "rule-based"
    if not hits:
        return {
            "content": "暂未检索到足够相似的历史应对案例，无法给出确定性结论，请结合人工研判。",
            "citations": [],
            "model": model,
            "promptVersion": PROMPT_VERSION,
        }
    citations = [{"caseId": h["case_id"], "title": h["case_title"], "excerpt": h["text"]} for h in hits]
    content = ""
    llm = LLMClient()
    if not llm.is_mock:
        try:
            excerpts = "\n".join(
                f"[案例{h['case_id']}] {h['case_title']}: {h['text']}" for h in hits
            )
            messages = [
                {"role": "system", "content": (
                    "你是企业舆情应对顾问。基于给定舆情背景与历史案例，输出 JSON："
                    "{content:string, citations:[{caseId:number, excerpt:string}]}。"
                    "必须引用案例编号且不得编造案例内容；证据不足时明确说明。"
                )},
                {"role": "user", "content": f"舆情背景：{json.dumps(context, ensure_ascii=False, default=str)[:6000]}\n\n历史案例：\n{excerpts}"},
            ]
            start = time.time()
            raw = llm.chat_json(messages, model=settings.llm_model_generation)
            _ = time.time() - start
            content = str(raw.get("content") or "")
            if content:
                model = settings.llm_model_generation
                known_ids = {h["case_id"] for h in hits}
                citations = [{
                    "caseId": c.get("caseId"),
                    "title": c.get("title", ""),
                    "excerpt": c.get("excerpt", ""),
                } for c in raw.get("citations", []) if c.get("caseId") in known_ids] or citations
        except (LLMError, ValueError, AttributeError) as exc:
            logger.warning("应对建议 LLM 生成失败，使用检索结果: %s", exc)
    return {
        "content": _content_from_hits(content, hits) if not content else content,
        "citations": citations,
        "model": model,
        "promptVersion": PROMPT_VERSION,
    }


def _content_from_hits(content: str, hits: list[dict]) -> str:
    if content:
        return content
    parts = [f"参考历史案例（{len(hits)} 条）："]
    for hit in hits:
        parts.append(f"- [{hit['case_id']}] {hit['case_title']}：{hit['text']}")
    return "\n".join(parts)


def _query_text(context: dict) -> str:
    parts = [
        context.get("monitorName", ""),
        context.get("title", ""),
        context.get("summary", ""),
        context.get("riskLevel", ""),
    ]
    trigger = context.get("triggerStats")
    if isinstance(trigger, dict):
        parts.append(str(trigger))
    return " ".join(p for p in parts if p)[:2000]