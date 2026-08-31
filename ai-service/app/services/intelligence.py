"""行业动态与竞品情报聚合：采集、去重、聚类和简报生成。

采集器只访问已配置的公开来源。LLM、Embedding、Playwright 均为可选能力，
未配置时使用规则化降级，保证任务状态和数据链路仍然可验收。
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ArticleCluster,
    CollectedArticle,
    CollectionTaskLog,
    IntelligenceReport,
    SourceConfig,
)
from .llm import LLMClient, LLMError
from .materials import embed_texts, _cosine

logger = logging.getLogger(__name__)


class ArticleHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self._skip += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"} and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        value = re.sub(r"\s+", " ", html.unescape(data or "")).strip()
        if not value:
            return
        if self._in_title and not self.title:
            self.title = value[:512]
        if not self._skip:
            self._parts.append(value)

    @property
    def text(self) -> str:
        return "\n".join(self._parts)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def is_source_due(source: SourceConfig, now: datetime | None = None) -> bool:
    """判断定时扫描时是否应为来源创建采集任务；手动来源不参与 Beat。"""
    interval_hours = {"hourly": 1, "daily": 24, "weekly": 24 * 7}.get(source.frequency)
    if interval_hours is None:
        return False
    if source.last_run_at is None:
        return True
    return (now or utcnow()) - source.last_run_at >= timedelta(hours=interval_hours)


def has_active_task(db: Session, source_id: int) -> bool:
    return db.query(CollectionTaskLog.id).filter(
        CollectionTaskLog.source_id == source_id,
        CollectionTaskLog.status.in_(("queued", "running")),
    ).first() is not None


def normalize_url(value: str) -> str:
    parts = urlsplit((value or "").strip())
    if not parts.scheme or not parts.netloc:
        return (value or "").strip()
    query = "&".join(p for p in parts.query.split("&") if p and not p.lower().startswith(("utm_", "spm=", "fbclid=")))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def normalize_text(value: str) -> str:
    value = html.unescape(value or "").lower()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def simhash(value: str, bits: int = 64) -> int:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_]+", normalize_text(value))
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


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def article_hash(title: str, content: str, url: str = "") -> str:
    normalized = normalize_text(title) + "\n" + normalize_text(content)
    return hashlib.sha256((normalized or normalize_url(url)).encode("utf-8")).hexdigest()


def _extract_html(raw: str, url: str) -> tuple[str, str]:
    try:
        import trafilatura

        title = trafilatura.extract_metadata(raw).title if trafilatura.extract_metadata(raw) else ""
        text = trafilatura.extract(raw, include_comments=False, include_tables=True) or ""
        if text.strip():
            return title or "", text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("trafilatura 抽取失败 %s: %s", url, exc)
    parser = ArticleHTMLParser()
    parser.feed(raw)
    return parser.title, parser.text


def _fetch_html(url: str) -> tuple[str, str, str]:
    headers = {"User-Agent": settings.collection_user_agent}
    with httpx.Client(timeout=settings.collection_timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        return response.text, content_type, str(response.url)


def _collect_rss(source: SourceConfig) -> list[dict]:
    import feedparser

    raw, _, final_url = _fetch_html(source.url)
    parsed = feedparser.parse(raw)
    items = []
    for entry in parsed.entries[: settings.collection_max_items]:
        url = normalize_url(entry.get("link") or final_url)
        title = (entry.get("title") or "").strip()
        summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or entry.get("description") or "")
        items.append({"title": title, "content": html.unescape(summary).strip(), "url": url, "author": entry.get("author", "")})
    return items


def _collect_api(source: SourceConfig) -> list[dict]:
    raw, _, final_url = _fetch_html(source.url)
    payload = json.loads(raw)
    if isinstance(payload, dict):
        for key in ("items", "articles", "data", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        payload = [payload]
    result = []
    for item in payload[: settings.collection_max_items]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "")
        content = str(item.get("content") or item.get("description") or item.get("summary") or "")
        url = normalize_url(str(item.get("url") or item.get("link") or final_url))
        if title or content:
            result.append({"title": title, "content": content, "url": url, "author": str(item.get("author") or "")})
    return result


def _collect_web(source: SourceConfig) -> list[dict]:
    raw, content_type, final_url = _fetch_html(source.url)
    title, content = _extract_html(raw, final_url)
    if not content.strip() and "html" in content_type:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(user_agent=settings.collection_user_agent)
                page.goto(source.url, wait_until="networkidle", timeout=settings.collection_timeout * 1000)
                title = page.title() or title
                content = page.locator("body").inner_text()
                browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Playwright 兜底不可用 %s: %s", source.url, exc)
    return [{"title": title or source.name, "content": content[:100000], "url": normalize_url(final_url or source.url), "author": ""}]


def collect_source(source: SourceConfig) -> list[dict]:
    if source.type == "rss":
        return _collect_rss(source)
    if source.type == "api":
        return _collect_api(source)
    return _collect_web(source)


def _matches_source(item: dict, source: SourceConfig) -> bool:
    # Source-level keyword fields are retained only for compatibility with the
    # intelligence module. Public-source collection itself must remain complete,
    # then each monitoring group performs its own explicit matching.
    return True


def persist_articles(db: Session, source: SourceConfig, raw_items: list[dict]) -> int:
    inserted = 0
    existing_hashes = {row[0] for row in db.query(CollectedArticle.content_hash).all()}
    for item in raw_items:
        if not _matches_source(item, source):
            continue
        title = str(item.get("title") or source.name).strip()[:512]
        content = str(item.get("content") or "").strip()
        url = normalize_url(str(item.get("url") or source.url))
        digest = article_hash(title, content, url)
        if digest in existing_hashes:
            continue
        db.add(CollectedArticle(
            source_id=source.id,
            title=title,
            content=content,
            url=url,
            author=str(item.get("author") or "")[:256],
            content_hash=digest,
            title_hash=f"{simhash(title):016x}",
            meta={"sourceName": source.name, "keywords": source.keywords or [], "competitors": source.competitors or []},
        ))
        existing_hashes.add(digest)
        inserted += 1
    db.commit()
    return inserted


def rebuild_clusters(db: Session, since_days: int = 30) -> list[ArticleCluster]:
    cutoff = utcnow() - timedelta(days=since_days)
    articles = db.query(CollectedArticle).filter(CollectedArticle.collected_at >= cutoff).order_by(CollectedArticle.collected_at.desc()).all()
    db.query(ArticleCluster).delete()
    groups: list[dict] = []
    for article in articles:
        signature = simhash(f"{article.title} {article.content[:3000]}")
        vector = article.embedding or []
        best = None
        best_score = 999
        for group in groups:
            distance = hamming_distance(signature, group["signature"])
            cosine = _cosine(vector, group["vector"]) if vector and group["vector"] else 0
            score = distance - cosine * 8
            if score < best_score:
                best, best_score = group, score
        if best is None or best_score > 18:
            best = {"signature": signature, "vector": vector, "articles": []}
            groups.append(best)
        best["articles"].append(article)
    clusters = []
    for group in groups:
        rows = group["articles"]
        topic = rows[0].title[:256] or "未命名主题"
        sources = sorted({str(row.source_id) for row in rows})
        cluster = ArticleCluster(
            topic=topic,
            article_ids=[row.id for row in rows],
            report_count=len(rows),
            time_start=min((row.publish_time or row.collected_at) for row in rows),
            time_end=max((row.publish_time or row.collected_at) for row in rows),
            sources=sources,
            meta={"dedupe": "simhash", "clusterScore": 1.0 if len(rows) == 1 else 0.5},
        )
        db.add(cluster)
        clusters.append(cluster)
    db.commit()
    return clusters


def _article_view(article: CollectedArticle, source_name: str = "") -> dict:
    return {
        "id": article.id,
        "sourceId": article.source_id,
        "sourceName": source_name,
        "title": article.title,
        "content": article.content[:2000],
        "url": article.url,
        "author": article.author,
        "publishTime": article.publish_time or article.collected_at,
        "collectedAt": article.collected_at,
        "sources": [{"id": article.source_id, "url": article.url, "title": article.title}],
        "generatedAt": article.collected_at,
        "model": "",
        "riskFlags": ["公开来源内容，发布前需人工核验"],
    }


def list_articles(db: Session, keyword: str = "", source_id: int | None = None, page: int = 1, page_size: int = 20) -> dict:
    query = db.query(CollectedArticle, SourceConfig.name).join(SourceConfig, SourceConfig.id == CollectedArticle.source_id)
    if source_id:
        query = query.filter(CollectedArticle.source_id == source_id)
    if keyword.strip():
        term = f"%{keyword.strip()}%"
        query = query.filter(or_(CollectedArticle.title.ilike(term), CollectedArticle.content.ilike(term)))
    total = query.count()
    rows = query.order_by(CollectedArticle.collected_at.desc()).offset(max(0, page - 1) * page_size).limit(min(page_size, 100)).all()
    return {"items": [_article_view(article, source_name) for article, source_name in rows], "total": total, "page": page, "pageSize": page_size}


def summarize_articles(db: Session, article_ids: list[int], cluster_id: int | None = None) -> dict:
    articles = db.query(CollectedArticle).filter(CollectedArticle.id.in_(article_ids)).order_by(CollectedArticle.collected_at.desc()).all()
    if not articles:
        return {"summary": "暂无可摘要的情报条目", "sources": [], "generatedAt": utcnow().isoformat(), "model": "rule-based", "riskFlags": ["未找到条目"]}
    source_map = {row.id: row.name for row in db.query(SourceConfig).all()}
    context = "\n".join(f"- {a.title}: {a.content[:1200]}" for a in articles)
    model = "rule-based"
    summary = "；".join(a.title for a in articles[:3])
    risk_flags = ["摘要基于公开来源，仅供决策参考"]
    llm = LLMClient()
    if not llm.is_mock:
        try:
            result = llm.chat_json([
                {"role": "system", "content": "你是企业情报分析员。仅根据输入材料输出 JSON：{summary:string, risks:string[]}，不得补造事实。"},
                {"role": "user", "content": context},
            ])
            summary = str(result.get("summary") or summary)
            risk_flags.extend(str(x) for x in result.get("risks", []) if x)
            model = settings.llm_model_generation
        except (LLMError, ValueError, AttributeError) as exc:
            logger.warning("情报摘要失败，使用规则化摘要: %s", exc)
    return {
        "summary": summary,
        "clusterId": cluster_id,
        "sources": [{"articleId": a.id, "sourceId": a.source_id, "sourceName": source_map.get(a.source_id, ""), "url": a.url, "title": a.title} for a in articles],
        "generatedAt": utcnow().isoformat(),
        "model": model,
        "riskFlags": risk_flags,
    }


def generate_report(db: Session, period: str = "daily") -> IntelligenceReport:
    now = utcnow()
    cutoff = now - timedelta(days=7 if period == "weekly" else 1)
    clusters = db.query(ArticleCluster).filter(ArticleCluster.time_end >= cutoff).order_by(ArticleCluster.report_count.desc()).limit(20).all()
    items = []
    all_ids = []
    for cluster in clusters:
        data = summarize_articles(db, cluster.article_ids[:8], cluster.id)
        cluster.summary = data["summary"]
        items.append({"clusterId": cluster.id, "topic": cluster.topic, "reportCount": cluster.report_count, **data})
        all_ids.extend(cluster.article_ids)
    report = IntelligenceReport(
        title=f"行业与竞品情报简报（{period}）",
        period=period,
        topic_tags=[cluster.topic for cluster in clusters[:10]],
        items=items,
        trend={"period": period, "articleCount": len(set(all_ids)), "clusterCount": len(clusters), "topTopics": [cluster.topic for cluster in clusters[:5]]},
        sources=[source_item for report_item in items for source_item in report_item.get("sources", [])],
        model="rule-based" if not settings.llm_api_key else settings.llm_model_generation,
        risk_flags=["情报简报为参考信息，重要结论需人工核验"],
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def run_collection_task(db: Session, task_id: int) -> None:
    task = db.get(CollectionTaskLog, task_id)
    if not task:
        return
    source = db.get(SourceConfig, task.source_id)
    if not source:
        task.status, task.error, task.finished_at = "failed", "采集源不存在", utcnow()
        db.commit()
        return
    task.status, task.started_at = "running", utcnow()
    source.last_run_at = task.started_at
    db.commit()
    try:
        items = collect_source(source)
        task.items_count = persist_articles(db, source, items)
        rebuild_clusters(db)
        source.health_status = "healthy"
        source.consecutive_failures = 0
        source.last_success_at = utcnow()
        source.last_error = ""
        task.status = "success"
    except Exception as exc:  # noqa: BLE001
        logger.exception("情报采集失败 source=%s", source.id)
        task.status = "failed"
        task.error = str(exc)[:4000]
        source.health_status = "degraded"
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
        source.last_error = str(exc)[:4000]
        if source.consecutive_failures >= settings.collection_failure_pause_after:
            source.status = "paused"
            source.health_status = "paused"
    task.finished_at = utcnow()
    db.commit()


def create_task(db: Session, source_id: int, retry_count: int = 0) -> CollectionTaskLog:
    task = CollectionTaskLog(source_id=source_id, status="queued", retry_count=retry_count)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task
