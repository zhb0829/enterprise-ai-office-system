from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import CollectionTaskLog, SourceConfig
from app.services.intelligence import (
    article_hash,
    hamming_distance,
    is_source_due,
    list_articles,
    persist_articles,
    rebuild_clusters,
    run_collection_task,
    simhash,
)


def make_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_simhash_is_stable_and_distance_is_small_for_similar_titles():
    left = simhash("某科技公司发布新一代企业 AI 助手")
    right = simhash("某科技公司发布企业AI助手新版本")
    assert left == simhash("某科技公司发布新一代企业 AI 助手")
    assert hamming_distance(left, right) < 24


def test_persist_articles_deduplicates_by_content_hash_and_clusters():
    db = make_db()
    source = SourceConfig(name="测试源", type="web", url="https://example.com", keywords=[], competitors=[])
    db.add(source)
    db.commit()

    first = {"title": "竞品发布 AI 助手", "content": "发布了新版本并公布功能。", "url": "https://example.com/a"}
    second = {"title": "竞品发布 AI 助手", "content": "发布了新版本并公布功能。", "url": "https://example.com/a?utm_source=x"}
    assert persist_articles(db, source, [first, second]) == 1
    assert article_hash(first["title"], first["content"], first["url"]) == article_hash(second["title"], second["content"], second["url"])
    clusters = rebuild_clusters(db)
    assert len(clusters) == 1
    assert clusters[0].report_count == 1


def test_list_articles_returns_pagination_shape():
    db = make_db()
    source = SourceConfig(name="测试源", type="rss", url="https://example.com/feed", keywords=[], competitors=[])
    db.add(source)
    db.commit()
    persist_articles(db, source, [{"title": "行业趋势", "content": "趋势正文", "url": "https://example.com/1"}])
    result = list_articles(db, keyword="趋势", page=1, page_size=10)
    assert result["total"] == 1
    assert result["items"][0]["title"] == "行业趋势"


def test_source_due_respects_frequency_and_skips_manual_sources():
    now = datetime(2026, 8, 22, 9, 0, 0)
    hourly = SourceConfig(name="小时源", type="rss", url="https://example.com/hourly", frequency="hourly", keywords=[], competitors=[])
    daily = SourceConfig(name="日源", type="rss", url="https://example.com/daily", frequency="daily", keywords=[], competitors=[], last_run_at=now - timedelta(hours=23))
    weekly = SourceConfig(name="周源", type="rss", url="https://example.com/weekly", frequency="weekly", keywords=[], competitors=[], last_run_at=now - timedelta(days=7))
    manual = SourceConfig(name="手动源", type="rss", url="https://example.com/manual", frequency="manual", keywords=[], competitors=[])

    assert is_source_due(hourly, now)
    assert not is_source_due(daily, now)
    assert is_source_due(weekly, now)
    assert not is_source_due(manual, now)


def test_collection_failure_is_persisted_for_celery_retry(monkeypatch):
    db = make_db()
    source = SourceConfig(name="失败源", type="web", url="https://example.com/fail", keywords=[], competitors=[])
    db.add(source)
    db.commit()
    task = CollectionTaskLog(source_id=source.id, status="queued")
    db.add(task)
    db.commit()

    monkeypatch.setattr("app.services.intelligence.collect_source", lambda _: (_ for _ in ()).throw(RuntimeError("network down")))
    run_collection_task(db, task.id)

    assert db.get(CollectionTaskLog, task.id).status == "failed"
    assert db.get(SourceConfig, source.id).health_status == "degraded"
