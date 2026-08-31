"""按会议关键词采集公开 RSS 补充报道。"""
from __future__ import annotations

from datetime import datetime

from ..config import settings


def collect_rss(conference: dict) -> list[dict]:
    import feedparser
    import trafilatura

    keywords = _keywords(conference)
    if not keywords:
        return []
    items = []
    seen = set()
    for feed_url in settings.meeting_rss_url_list:
        feed = feedparser.parse(feed_url)
        source_name = str(getattr(feed.feed, "title", "") or feed_url)
        for entry in feed.entries:
            title = str(getattr(entry, "title", "") or "")
            if not any(keyword.lower() in title.lower() for keyword in keywords):
                continue
            url = str(getattr(entry, "link", "") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            summary = str(getattr(entry, "summary", "") or "")
            try:
                downloaded = trafilatura.fetch_url(url)
                extracted = trafilatura.extract(downloaded) if downloaded else ""
                if extracted:
                    summary = extracted[:1200]
            except Exception:  # noqa: BLE001
                pass
            items.append({
                "title": title,
                "sourceUrl": url,
                "sourceName": source_name,
                "publishedAt": _published(entry),
                "summary": summary[:2000],
                "contentPath": "",
            })
            if len(items) >= 50:
                return items
    return items


def _keywords(conference: dict) -> list[str]:
    raw = str(conference.get("keywords") or "")
    values = [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]
    if conference.get("name"):
        values.append(str(conference["name"]).strip())
    return list(dict.fromkeys(values))


def _published(entry) -> str:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return ""
    return datetime(*parsed[:6]).isoformat()
