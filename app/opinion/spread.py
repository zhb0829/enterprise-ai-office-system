"""传播路径分析。

已验证关系：文章正文/标题存在明确转载、引用线索（如“转载自…”）。
推测关系：基于标题与正文相似度 + 发布时间先后推断。
两类关系分别返回，由 Java 权威落库并区分 verified 标记。
"""
from __future__ import annotations

import hashlib
import html
import logging
import re

logger = logging.getLogger(__name__)


def _normalize_text(value: str) -> str:
    value = html.unescape(value or "").lower()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _simhash(value: str, bits: int = 64) -> int:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_]+", _normalize_text(value))
    if not tokens:
        return 0
    weights = [0] * bits
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        number = int.from_bytes(digest[:8], "big")
        for index in range(bits):
            weights[index] += 1 if number & (1 << index) else -1
    result = 0
    for index, weight in enumerate(weights):
        if weight >= 0:
            result |= 1 << index
    return result


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def analyze(monitor_id: int, articles: list[dict]) -> dict:
    """计算传播边。articles 需含 id/title/content/url/sourceId/collectedAt。"""
    if not articles or len(articles) < 2:
        return {"monitorId": monitor_id, "edges": []}

    rows = []
    for article in articles:
        title = str(article.get("title") or "")
        rows.append({
            "id": int(article.get("id") or 0),
            "title": title,
            "content": str(article.get("content") or ""),
            "url": str(article.get("url") or ""),
            "collectedAt": str(article.get("collectedAt") or ""),
            "signature": _simhash(title + " " + (article.get("content") or "")[:3000]),
        })

    edges: list[dict] = []
    seen: set[tuple[int, int, str]] = set()
    for i in range(len(rows)):
        for j in range(len(rows)):
            if i == j:
                continue
            a, b = rows[i], rows[j]
            if a["id"] == b["id"]:
                continue
            verified = _verified_edge(a, b)
            inferred = _inferred_edge(a, b)
            candidates = verified + inferred
            for candidate in candidates:
                key = (candidate["fromArticleId"], candidate["toArticleId"], candidate["relationType"])
                if key in seen:
                    continue
                seen.add(key)
                edges.append(candidate)

    edges.sort(key=lambda e: e.get("confidence", 0), reverse=True)
    return {"monitorId": monitor_id, "edges": edges[:200]}


def _verified_edge(a: dict, b: dict) -> list[dict]:
    """a 更晚发布且明确引用 b 的标题 → 已验证转载/引用。"""
    a_text = _normalize_text(a["title"] + " " + a["content"])
    b_title = _normalize_text(b["title"])
    if not b_title:
        return []
    markers = ["转载自", "转自", "来源：", "来源:", "本文转载", "引用自", "综合"]
    for marker in markers:
        idx = a_text.find(marker)
        if idx != -1 and b_title in a_text:
            return [{
                "fromArticleId": a["id"],
                "toArticleId": b["id"],
                "relationType": "转载" if "转载" in marker or "转自" in marker else "引用",
                "verified": True,
                "evidence": f"正文含「{marker}」且引用标题《{b['title']}》",
                "confidence": 0.95,
            }]
    return []


def _inferred_edge(a: dict, b: dict) -> list[dict]:
    """相似度 + 时间推断：较早文章 → 较晚文章（推测关系，不作正式事实）。"""
    distance = _hamming(a["signature"], b["signature"])
    similarity = 1.0 - distance / 64.0
    if similarity < 0.55:
        return []
    earlier, later = (a, b) if a["collectedAt"] <= b["collectedAt"] else (b, a)
    confidence = round(min(0.9, similarity * 0.8 + 0.1), 4)
    return [{
        "fromArticleId": earlier["id"],
        "toArticleId": later["id"],
        "relationType": "相似",
        "verified": False,
        "evidence": f"内容相似度 {round(similarity, 2)}（simhash 距离 {distance}），发布时间先后推断",
        "confidence": confidence,
    }]