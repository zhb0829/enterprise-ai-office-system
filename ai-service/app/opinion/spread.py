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
from datetime import datetime

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


def _timestamp(value: str) -> float:
    raw = str(value or "").strip()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def analyze(monitor_id: int, articles: list[dict]) -> dict:
    """计算传播边。articles 需含 id/title/content/url/sourceId/publishTime。"""
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
            "publishTime": str(article.get("publishTime") or article.get("collectedAt") or ""),
            "publishedAt": _timestamp(article.get("publishTime") or article.get("collectedAt") or ""),
            "signature": _simhash(title + " " + (article.get("content") or "")[:3000]),
        })

    edges: list[dict] = []
    ordered = sorted(rows, key=lambda item: (item["publishedAt"], item["id"]))
    for index, later in enumerate(ordered):
        verified_candidates: list[dict] = []
        inferred_candidates: list[tuple[float, dict]] = []
        for earlier in ordered[:index]:
            verified = _verified_edge(earlier, later)
            if verified:
                verified_candidates.extend(verified)
                continue
            inferred = _inferred_edge(earlier, later)
            if not inferred:
                continue
            inferred_candidates.append((earlier["publishedAt"], inferred[0]))

        # 明确转载/引用优先；否则每篇文章只保留一个最可能的上游，形成可读的传播主路径。
        if verified_candidates:
            edges.extend(sorted(
                verified_candidates,
                key=lambda edge: edge["confidence"],
                reverse=True,
            ))
        elif inferred_candidates:
            best_confidence = max(candidate[1]["confidence"] for candidate in inferred_candidates)
            plausible = [
                candidate for candidate in inferred_candidates
                if candidate[1]["confidence"] >= best_confidence - 0.05
            ]
            edges.append(max(
                plausible,
                key=lambda candidate: (candidate[0], candidate[1]["confidence"]),
            )[1])

    edges.sort(key=lambda e: e.get("confidence", 0), reverse=True)
    return {"monitorId": monitor_id, "edges": edges[:200]}


def _verified_edge(earlier: dict, later: dict) -> list[dict]:
    """较晚文章明确引用较早文章标题时，返回“原文 → 转载/引用”的已验证关系。"""
    later_text = _normalize_text(later["title"] + " " + later["content"])
    earlier_title = _normalize_text(earlier["title"])
    if not earlier_title:
        return []
    markers = ["转载自", "转自", "来源：", "来源:", "本文转载", "引用自", "综合"]
    for marker in markers:
        if marker in later_text and earlier_title in later_text:
            return [{
                "fromArticleId": earlier["id"],
                "toArticleId": later["id"],
                "relationType": "转载" if "转载" in marker or "转自" in marker else "引用",
                "verified": True,
                "evidence": f"正文含「{marker}」且引用标题《{earlier['title']}》",
                "confidence": 0.95,
            }]
    return []


def _inferred_edge(earlier: dict, later: dict) -> list[dict]:
    """相似度 + 时间推断：较早文章 → 较晚文章（推测关系，不作正式事实）。"""
    distance = _hamming(earlier["signature"], later["signature"])
    similarity = 1.0 - distance / 64.0
    if similarity < 0.55:
        return []
    confidence = round(min(0.9, similarity * 0.8 + 0.1), 4)
    return [{
        "fromArticleId": earlier["id"],
        "toArticleId": later["id"],
        "relationType": "相似",
        "verified": False,
        "evidence": f"内容相似度 {round(similarity, 2)}（simhash 距离 {distance}），发布时间先后推断",
        "confidence": confidence,
    }]
