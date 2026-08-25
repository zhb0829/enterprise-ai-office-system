"""公开采集源适配器。

只采集公开渠道：新闻/RSS/官方 API/授权公开网页。不侵入私域、不绕过访问控制。
每类来源独立实现一个适配函数，避免将所有平台逻辑写入单一采集器。
清洗与去重辅助能力在此完成，最终的归一化/匹配/入库由 Java 权威服务执行。
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


def normalize_url(value: str) -> str:
    parts = urlsplit((value or "").strip())
    if not parts.scheme or not parts.netloc:
        return (value or "").strip()
    query = "&".join(
        p for p in parts.query.split("&")
        if p and not p.lower().startswith(("utm_", "spm=", "fbclid="))
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def validate_public_url(value: str) -> str:
    url = (value or "").strip()
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("source URL must be a public http/https URL")
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("local source URLs are not allowed")
    try:
        addresses = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80),
                                       type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("source hostname cannot be resolved") from exc
    for _, _, _, _, sockaddr in addresses:
        address = ipaddress.ip_address(sockaddr[0])
        if (address.is_private or address.is_loopback or address.is_link_local
                or address.is_multicast or address.is_unspecified):
            raise ValueError("private or local source address is not allowed")
    return normalize_url(url)


def normalize_text(value: str) -> str:
    value = html.unescape(value or "").lower()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def sha256(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def content_hash(title: str, content: str, url: str = "") -> str:
    normalized = normalize_text(title) + "\n" + normalize_text(content)
    if not normalized:
        normalized = normalize_text(url)
    return sha256(normalized)


def url_hash(url: str) -> str:
    return sha256(normalize_url(url))


def clean_text(value: str, limit: int = 200000) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[ \t\r\n\f\v]+", " ", value)
    return value.strip()[:limit]


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header"}:
            self._skip += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript", "svg", "nav", "footer", "header"} and self._skip:
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


def _extract_html(raw: str, url: str) -> tuple[str, str]:
    try:
        import trafilatura

        metadata = trafilatura.extract_metadata(raw)
        title = (metadata.title or "") if metadata else ""
        text = trafilatura.extract(raw, include_comments=False, include_tables=True) or ""
        if text.strip():
            return title or "", text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("trafilatura 抽取失败 %s: %s", url, exc)
    parser = TextExtractor()
    parser.feed(raw)
    return parser.title, parser.text


def _fetch(url: str, method: str = "get", data: dict | None = None) -> str:
    url = validate_public_url(url)
    headers = {"User-Agent": settings.collection_user_agent}
    with httpx.Client(timeout=settings.collection_timeout, follow_redirects=False, headers=headers) as client:
        if method == "post":
            response = client.post(url, json=data)
        else:
            response = client.get(url)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location", "")
            if not location:
                raise ValueError("source redirect has no location")
            redirected = validate_public_url(str(httpx.URL(url).join(location)))
            response = client.post(redirected, json=data) if method == "post" else client.get(redirected)
        response.raise_for_status()
        return response.text


def _fetch_url(url: str) -> str:
    """Webcollector 固定用 GET；带参与方法由来源配置决定。"""
    return _fetch(url)


def _item(title: str, content: str, url: str, author: str = "", publish_time: str = "") -> dict:
    title = (title or "").strip()[:512]
    content = clean_text(content)
    url = normalize_url(url)
    return {
        "title": title,
        "content": content,
        "url": url,
        "url_hash": url_hash(url),
        "author": (author or "").strip()[:256],
        "publish_time": publish_time or None,
        "content_hash": content_hash(title, content, url),
    }


def collect_rss(source: dict) -> list[dict]:
    import feedparser

    raw = _fetch_url(source["homepage"])
    parsed = feedparser.parse(raw)
    items: list[dict] = []
    for entry in parsed.entries[: settings.opinion_max_articles_per_source]:
        url = normalize_url(entry.get("link") or source["homepage"])
        title = entry.get("title") or ""
        summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or entry.get("description") or "")
        published = ""
        for key in ("published_parsed", "updated_parsed"):
            value = entry.get(key)
            if value:
                try:
                    published = _rss_to_iso(value)
                except Exception:  # noqa: BLE001
                    published = ""
                break
        items.append(_item(title, html.unescape(summary), url, entry.get("author", ""), published))
    return items


def collect_api(source: dict) -> list[dict]:
    raw = _fetch(source["homepage"], method="post" if source.get("collect_method") == "post" else "get")
    payload = json.loads(raw)
    if isinstance(payload, dict):
        for key in ("items", "articles", "data", "results", "list"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        payload = [payload]
    items: list[dict] = []
    for item in payload[: settings.opinion_max_articles_per_source]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "")
        content = str(item.get("content") or item.get("description") or item.get("summary") or item.get("body") or "")
        url = str(item.get("url") or item.get("link") or source["homepage"])
        author = str(item.get("author") or item.get("source") or "")
        items.append(_item(title, content, url, author))
    return items


def collect_web(source: dict) -> list[dict]:
    url = source["homepage"]
    raw = _fetch_url(url)
    title, content = _extract_html(raw, url)
    if not content.strip() and "html" in raw.lower():
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page(user_agent=settings.collection_user_agent)
                page.goto(url, wait_until="networkidle", timeout=settings.collection_timeout * 1000)
                title = page.title() or title
                content = page.locator("body").inner_text()
                browser.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Playwright 兜底不可用 %s: %s", url, exc)
    return [_item(title or source["name"], content, url)]


def collect(source: dict) -> list[dict]:
    """按来源类型分派到独立适配器。"""
    source_type = (source.get("source_type") or "web").lower()
    if source_type == "rss":
        return collect_rss(source)
    if source_type == "api":
        return collect_api(source)
    return collect_web(source)


def dedupe(items: list[dict]) -> list[dict]:
    """批内去重：同一 content_hash 只保留一条。"""
    seen: set[str] = set()
    unique: list[dict] = []
    for item in items:
        key = item.get("content_hash") or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _rss_to_iso(value) -> str:
    """把 feedparser 的 struct_time / datetime 直接转字符串并交给 Java 解析。"""
    if hasattr(value, "year") and hasattr(value, "minute"):
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d} {value.hour:02d}:{value.minute:02d}:00"
    return ""
