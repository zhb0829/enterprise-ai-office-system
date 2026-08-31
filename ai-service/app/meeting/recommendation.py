"""政策与历史会议关联推荐，各取 top5，阈值 0.72。"""
from __future__ import annotations

import math
import re

from sqlalchemy import text

from ..db import engine
from ..services.materials import embed_texts

THRESHOLD = 0.72


def recommend(conference: dict, report: str) -> tuple[list[dict], list[dict]]:
    query = " ".join(filter(None, [
        str(conference.get("name") or ""),
        str(conference.get("keywords") or ""),
        str(conference.get("description") or ""),
        report[:3000],
    ]))
    policies = _rank(query, _policy_candidates(), "policy")
    conferences = _rank(query, _conference_candidates(int(conference.get("id") or 0)), "conference")
    return policies[:5], conferences[:5]


def _policy_candidates() -> list[dict]:
    sql = text("""
        SELECT id, title, doc_number, issuing_authority, text_content
        FROM policy_document
        WHERE parse_status IN ('已完成', 'completed', 'parsed')
        ORDER BY publish_date DESC NULLS LAST, id DESC
        LIMIT 300
    """)
    try:
        with engine.connect() as connection:
            return [{
                "id": row.id,
                "title": row.title,
                "docNumber": row.doc_number,
                "authority": row.issuing_authority,
                "text": (row.text_content or "")[:4000],
            } for row in connection.execute(sql)]
    except Exception:  # noqa: BLE001
        return []


def _conference_candidates(current_id: int) -> list[dict]:
    sql = text("""
        SELECT c.id, c.name, c.organizer, c.keywords, r.content
        FROM conference c
        JOIN LATERAL (
            SELECT content FROM conference_report
            WHERE conference_id = c.id ORDER BY version DESC LIMIT 1
        ) r ON TRUE
        WHERE c.id <> :current_id AND c.status = 'completed' AND c.archived = FALSE
        ORDER BY c.start_time DESC NULLS LAST, c.id DESC
        LIMIT 300
    """)
    try:
        with engine.connect() as connection:
            return [{
                "id": row.id,
                "title": row.name,
                "organizer": row.organizer,
                "keywords": row.keywords,
                "text": (row.content or "")[:4000],
            } for row in connection.execute(sql, {"current_id": current_id})]
    except Exception:  # noqa: BLE001
        return []


def _rank(query: str, candidates: list[dict], related_type: str) -> list[dict]:
    if not query.strip() or not candidates:
        return []
    texts = [query, *[_candidate_text(item) for item in candidates]]
    try:
        vectors = embed_texts(texts)
    except Exception:  # noqa: BLE001
        vectors = []
    query_terms = _terms(query)
    ranked = []
    for index, item in enumerate(candidates):
        candidate_text = _candidate_text(item)
        lexical = _overlap(query_terms, _terms(candidate_text))
        semantic = _cosine(vectors[0], vectors[index + 1]) if len(vectors) == len(texts) else 0
        score = max(lexical, semantic)
        if score < THRESHOLD:
            continue
        ranked.append({
            **{key: value for key, value in item.items() if key != "text"},
            "relatedType": related_type,
            "score": round(float(score), 4),
            "reason": _reason(query_terms, candidate_text),
        })
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def _candidate_text(item: dict) -> str:
    return " ".join(str(item.get(key) or "") for key in ("title", "docNumber", "authority", "organizer", "keywords", "text"))


def _terms(value: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fa5]{2,8}|[A-Za-z0-9_.%-]+", value.lower()))


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / math.sqrt(len(left) * len(right))


def _reason(query_terms: set[str], candidate_text: str) -> str:
    hits = [term for term in query_terms if term in candidate_text.lower()]
    return "共同涉及：" + "、".join(hits[:5]) if hits else "主题语义相近"


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(v * v for v in left)) * math.sqrt(sum(v * v for v in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0
