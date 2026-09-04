"""行业动态与竞品情报聚合：采集、去重、聚类和简报生成（Java 权威数据面）。

Java 拥有 source_config / collected_article / article_cluster / intelligence_report /
collection_task_log 等全部情报表。本模块只保留采集器与 AI 能力：抓取、simhash、
向量聚类与 LLM 摘要均为本地计算，读写一律经 ``IntelligenceJavaClient`` 完成。
采集器只访问已配置的公开来源。LLM、Embedding、Playwright 均为可选能力，
未配置时使用规则化降级，保证任务状态和数据链路仍然可验收。
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..config import settings
from .llm import LLMClient, LLMError
from .materials import _cosine
from .intelligence_client import IntelligenceJavaClient, IntelligenceJavaError, java_client  # noqa: F401

logger = logging.getLogger(__name__)


class CollectionRunError(RuntimeError):
    """采集执行失败（任务与来源状态已回写 Java，调用方按需重试）。"""


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


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# ---------- 纯算法工具（不依赖 DB） ----------


def is_source_due(source: dict, now: datetime | None = None) -> bool:
    """判断定时扫描时是否应为来源创建采集任务；手动来源不参与 Beat。"""
    interval_hours = {"hourly": 1, "daily": 24, "weekly": 24 * 7}.get(str(source.get("frequency")))
    if interval_hours is None:
        return False
    last_run = source.get("lastRunAt")
    if not last_run:
        return True
    try:
        last = datetime.fromisoformat(str(last_run))
    except ValueError:
        return True
    return (now or utcnow()) - last >= timedelta(hours=interval_hours)


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
        if weight > 0:
            result |= 1 << index
    return result


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def article_hash(title: str, content: str, url: str = "") -> str:
    normalized = normalize_text(title) + "\n" + normalize_text(content)
    return hashlib.sha256((normalized or normalize_url(url)).encode("utf-8")).hexdigest()


# ---------- 采集（网络抓取，输入/输出均为 dict） ----------


def _extract_html(raw: str, url: str) -> tuple[str, str]:
    try:
        import trafilatura

        metadata = trafilatura.extract_metadata(raw)
        title = metadata.title if metadata else ""
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


def _collect_rss(source: dict) -> list[dict]:
    import feedparser

    raw, _, final_url = _fetch_html(source["url"])
    parsed = feedparser.parse(raw)
    items = []
    for entry in parsed.entries[: settings.collection_max_items]:
        url = normalize_url(entry.get("link") or final_url)
        title = (entry.get("title") or "").strip()
        summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or entry.get("description") or "")
        items.append({"title": title, "content": html.unescape(summary).strip(), "url": url, "author": entry.get("author", "")})
    return items


def _collect_api(source: dict) -> list[dict]:
    raw, _, final_url = _fetch_html(source["url"])
    payload = json_loads(raw)
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


def _collect_web(source: dict) -> list[dict]:
    raw, content_type, final_url = _fetch_html(source["url"])
    title, content = _extract_html(raw, final_url)
    if not content.strip() and "html" in content_type:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(user_agent=settings.collection_user_agent)
                page.goto(source["url"], wait_until="networkidle", timeout=settings.collection_timeout * 1000)
                title = page.title() or title
                content = page.locator("body").inner_text()
                browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Playwright 兜底不可用 %s: %s", source.get("url"), exc)
    return [{"title": title or source.get("name", ""), "content": content[:100000], "url": normalize_url(final_url or source.get("url", "")), "author": ""}]


def json_loads(raw: str):
    import json

    return json.loads(raw)


def collect_source(source: dict) -> list[dict]:
    source_type = str(source.get("type"))
    if source_type == "rss":
        return _collect_rss(source)
    if source_type == "api":
        return _collect_api(source)
    return _collect_web(source)


def _matches_source(item: dict, source: dict) -> bool:
    # 公开来源需完整采集，具体命中断言由各监控域自行完成。
    return True


def build_ingest_items(source: dict, raw_items: list[dict]) -> list[dict]:
    """把抓取结果换算成 Java 入库载荷（按既有算法计算 content_hash/title_hash）。"""
    payload: list[dict] = []
    for item in raw_items:
        if not _matches_source(item, source):
            continue
        title = str(item.get("title") or source.get("name", "")).strip()[:512]
        content = str(item.get("content") or "").strip()
        url = normalize_url(str(item.get("url") or source.get("url", "")))
        digest = article_hash(title, content, url)
        payload.append(
            {
                "title": title,
                "content": content,
                "url": url,
                "author": str(item.get("author") or "")[:256],
                "contentHash": digest,
                "titleHash": f"{simhash(title):016x}",
                "status": "new",
                "embedding": [],
                "meta": {
                    "sourceName": source.get("name", ""),
                    "keywords": source.get("keywords") or [],
                    "competitors": source.get("competitors") or [],
                },
            }
        )
    return payload


# ---------- 面向用户/报告展示的视图 ----------


def article_view(article: dict) -> dict:
    return {
        "id": article.get("id"),
        "sourceId": article.get("sourceId"),
        "sourceName": article.get("sourceName", ""),
        "title": article.get("title", ""),
        "content": str(article.get("content") or "")[:2000],
        "url": article.get("url", ""),
        "author": article.get("author", ""),
        "publishTime": article.get("publishTime"),
        "collectedAt": article.get("collectedAt"),
        "sources": [
            {
                "id": article.get("sourceId"),
                "url": article.get("url", ""),
                "title": article.get("title", ""),
                "sourceName": article.get("sourceName", ""),
            }
        ],
        "generatedAt": article.get("collectedAt"),
        "model": "",
        "riskFlags": ["公开来源内容，发布前需人工核验"],
    }


def list_articles(keyword: str = "", source_id: int | None = None, page: int = 1, page_size: int = 20) -> dict:
    data = java_client.list_articles(keyword=keyword, source_id=source_id, page=page, page_size=page_size)
    items = [article_view(row) for row in (data.get("items") or [])]
    return {"items": items, "total": data.get("total", 0), "page": page, "pageSize": page_size}


def summarize_articles(article_ids: list[int], cluster_id: int | None = None) -> dict:
    if not article_ids:
        return {"summary": "暂无可摘要的情报条目", "sources": [], "generatedAt": _iso(utcnow()), "model": "rule-based", "riskFlags": ["未找到条目"]}
    articles = java_client.list_articles_by_ids(article_ids)
    if not articles:
        return {"summary": "暂无可摘要的情报条目", "sources": [], "generatedAt": _iso(utcnow()), "model": "rule-based", "riskFlags": ["未找到条目"]}
    context = "\n".join(f"- {a.get('title', '')}: {str(a.get('content') or '')[:1200]}" for a in articles)
    model = "rule-based"
    summary = "；".join(str(a.get("title", "")) for a in articles[:3])
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
        "sources": [
            {
                "articleId": a.get("id"),
                "sourceId": a.get("sourceId"),
                "sourceName": a.get("sourceName", ""),
                "url": a.get("url", ""),
                "title": a.get("title", ""),
            }
            for a in articles
        ],
        "generatedAt": _iso(utcnow()),
        "model": model,
        "riskFlags": risk_flags,
    }


# ---------- 聚类 ----------


def _fetch_recent_articles(since_days: int, page_size: int = 100) -> list[dict]:
    """分页拉取 Java 权威表中的近期文章（含 embedding）。"""
    rows: list[dict] = []
    page = 1
    while True:
        data = java_client.list_articles(since_days=since_days, page=page, page_size=page_size)
        items = data.get("items") or []
        rows.extend(items)
        total = int(data.get("total") or 0)
        if len(rows) >= total or not items:
            break
        page += 1
    return rows


def rebuild_clusters(since_days: int = 30) -> list[dict]:
    """读取近期文章 → 本地 simhash+cosine 聚类 → 全量重建回写 Java article_cluster。"""
    articles = _fetch_recent_articles(since_days)
    groups: list[dict] = []
    for article in articles:
        signature = simhash(f"{article.get('title', '')} {str(article.get('content') or '')[:3000]}")
        vector = article.get("embedding") or []
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

    clusters: list[dict] = []
    for group in groups:
        rows = group["articles"]
        topic = str(rows[0].get("title", ""))[:256] or "未命名主题"
        sources = sorted({str(row.get("sourceId")) for row in rows if row.get("sourceId") is not None})
        times = [
            datetime.fromisoformat(str(row.get("publishTime") or row.get("collectedAt")))
            for row in rows
            if (row.get("publishTime") or row.get("collectedAt"))
        ]
        clusters.append(
            {
                "topic": topic,
                "summary": "",
                "articleIds": [row.get("id") for row in rows],
                "reportCount": len(rows),
                "timeStart": _iso(min(times)) if times else None,
                "timeEnd": _iso(max(times)) if times else None,
                "sources": sources,
                "meta": {"dedupe": "simhash", "clusterScore": 1.0 if len(rows) == 1 else 0.5},
            }
        )
    java_client.replace_clusters(clusters)
    return clusters


# ---------- 简报 ----------


def generate_report(period: str = "daily") -> dict:
    """读取近期聚类 → 逐簇摘要 → 组装并保存简报（Java intelligence_report）→ 回写聚类摘要。"""
    now = utcnow()
    days = 7 if period == "weekly" else 1
    clusters = java_client.list_clusters(since_days=days, limit=50)
    top = clusters[:20]
    items = []
    all_ids: list[int] = []
    enriched: list[dict] = []
    for cluster in top:
        ids = [int(i) for i in (cluster.get("articleIds") or [])]
        data = summarize_articles(ids, cluster.get("id"))
        cluster["summary"] = data["summary"]
        items.append(
            {
                "clusterId": cluster.get("id"),
                "topic": cluster.get("topic"),
                "reportCount": cluster.get("reportCount"),
                **data,
            }
        )
        all_ids.extend(ids)
        enriched.append(cluster)
    if enriched:
        java_client.replace_clusters(enriched)
    report = {
        "title": f"行业与竞品情报简报（{period}）",
        "period": period,
        "topicTags": [cluster.get("topic") for cluster in top[:10]],
        "items": items,
        "trend": {
            "period": period,
            "articleCount": len(set(all_ids)),
            "clusterCount": len(top),
            "topTopics": [cluster.get("topic") for cluster in top[:5]],
        },
        "sources": [source_item for report_item in items for source_item in report_item.get("sources", [])],
        "model": "rule-based" if not settings.llm_api_key else settings.llm_model_generation,
        "riskFlags": ["情报简报为参考信息，重要结论需人工核验"],
        "generatedAt": _iso(now),
    }
    return java_client.save_report(report)


# ---------- 任务执行（Worker） ----------


def _mark_source_failure(source_id: int, error: str) -> None:
    try:
        source = java_client.get_source(source_id)
    except IntelligenceJavaError:
        logger.exception("读取采集源状态失败 source=%s", source_id)
        return
    if not source:
        return
    failures = int(source.get("consecutiveFailures") or 0) + 1
    state = {
        "healthStatus": "degraded",
        "consecutiveFailures": failures,
        "lastError": str(error)[:4000],
    }
    if failures >= settings.collection_failure_pause_after and source.get("status") != "paused":
        state["healthStatus"] = "paused"
        state["status"] = "paused"
    java_client.update_source_run_state(source_id, state)


def run_collection_task(task_id: int) -> dict | None:
    """采集任务执行：任务与来源状态均由 Java 权威保存，本函数负责编排与回写。"""
    task = java_client.get_task(task_id)
    if not task:
        return None
    source_id = int(task.get("sourceId"))
    java_client.mark_task_start(task_id)
    java_client.update_source_run_state(source_id, {"lastRunAt": _iso(utcnow())})
    try:
        source = java_client.get_source(source_id)
        if not source:
            raise CollectionRunError(f"采集源不存在 source={source_id}")
        items = collect_source(source)
        payload = build_ingest_items(source, items)
        result = java_client.ingest_articles(source_id, payload)
        inserted = int(result.get("inserted") or 0)
        java_client.update_source_run_state(
            source_id,
            {
                "healthStatus": "healthy",
                "consecutiveFailures": 0,
                "lastSuccessAt": _iso(utcnow()),
                "lastError": "",
            },
        )
        java_client.mark_task_result(task_id, inserted)
        return java_client.get_task(task_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("情报采集失败 task=%s source=%s", task_id, source_id)
        try:
            _mark_source_failure(source_id, str(exc))
            java_client.mark_task_failure(task_id, str(exc))
        except IntelligenceJavaError:
            logger.exception("回写失败状态失败 task=%s", task_id)
        raise CollectionRunError(str(exc)) from exc
