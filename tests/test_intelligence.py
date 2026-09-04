from datetime import datetime, timedelta

import pytest

from app.services import intelligence as svc
from app.services.intelligence import (
    article_hash,
    build_ingest_items,
    hamming_distance,
    is_source_due,
    rebuild_clusters,
    run_collection_task,
    simhash,
)


class FakeJavaClient:
    """IntelligenceJavaClient 替身：记录调用并返回可编排数据。"""

    def __init__(self):
        self.articles = []
        self.sources = {}
        self.tasks = {}
        self.replaced_clusters = None
        self.saved_report = None
        self.updated_run_states = []
        self.started = []
        self.failed = []
        self.resulted = []

    # 文章
    def list_articles(self, since_days=None, keyword="", source_id=None, page=1, page_size=20):
        start = (page - 1) * page_size
        return {"items": self.articles[start : start + page_size], "total": len(self.articles)}

    def list_articles_by_ids(self, ids):
        wanted = set(ids)
        return [a for a in self.articles if a.get("id") in wanted]

    def ingest_articles(self, source_id, items):
        return {"inserted": len(items), "skipped": 0}

    # 来源
    def get_source(self, source_id):
        return self.sources.get(source_id)

    def update_source_run_state(self, source_id, state):
        self.updated_run_states.append((source_id, state))
        current = self.sources.setdefault(source_id, {"id": source_id, "status": "enabled"})
        current.update(state)
        return current

    # 聚类
    def replace_clusters(self, clusters):
        self.replaced_clusters = clusters
        return {"created": len(clusters)}

    def list_clusters(self, since_days=None, topic="", limit=50):
        return []

    def get_cluster(self, cluster_id):
        return None

    # 任务
    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def mark_task_start(self, task_id):
        self.started.append(task_id)
        return {"id": task_id, "status": "running"}

    def mark_task_result(self, task_id, items_count):
        self.resulted.append((task_id, items_count))
        return {"id": task_id, "status": "success"}

    def mark_task_failure(self, task_id, error):
        self.failed.append((task_id, error))
        return {"id": task_id, "status": "failed"}

    # 简报
    def save_report(self, payload):
        self.saved_report = payload
        return {**payload, "id": 1}


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeJavaClient()
    monkeypatch.setattr(svc, "java_client", client)
    return client


def test_simhash_is_stable_and_distance_is_small_for_similar_titles():
    left = simhash("某科技公司发布新一代企业 AI 助手")
    right = simhash("某科技公司发布企业AI助手新版本")
    assert left == simhash("某科技公司发布新一代企业 AI 助手")
    assert hamming_distance(left, right) < 24


def test_article_hash_ignores_tracking_query_params():
    first = {"title": "竞品发布 AI 助手", "content": "发布了新版本并公布功能。", "url": "https://example.com/a"}
    second = {"title": "竞品发布 AI 助手", "content": "发布了新版本并公布功能。", "url": "https://example.com/a?utm_source=x"}
    assert article_hash(first["title"], first["content"], first["url"]) == article_hash(second["title"], second["content"], second["url"])


def test_build_ingest_items_uses_stable_hashes():
    source = {"name": "测试源", "type": "web", "url": "https://example.com", "keywords": ["AI"], "competitors": []}
    items = [
        {"title": "竞品发布 AI 助手", "content": "发布了新版本并公布功能。", "url": "https://example.com/a"},
        {"title": "竞品发布 AI 助手", "content": "发布了新版本并公布功能。", "url": "https://example.com/a?utm_source=x"},
    ]
    payload = build_ingest_items(source, items)
    assert len(payload) == 2
    assert payload[0]["contentHash"] == payload[1]["contentHash"]
    assert payload[0]["meta"]["sourceName"] == "测试源"


def test_is_source_due_respects_frequency_and_skips_manual_sources():
    now = datetime(2026, 8, 22, 9, 0, 0)
    hourly = {"frequency": "hourly"}
    daily = {"frequency": "daily", "lastRunAt": (now - timedelta(hours=23)).isoformat()}
    weekly = {"frequency": "weekly", "lastRunAt": (now - timedelta(days=7)).isoformat()}
    manual = {"frequency": "manual", "lastRunAt": now.isoformat()}

    assert is_source_due(hourly, now)
    assert not is_source_due(daily, now)
    assert is_source_due(weekly, now)
    assert not is_source_due(manual, now)


def test_rebuild_clusters_clusters_similar_articles(fake_client):
    base = datetime(2026, 8, 22, 9, 0, 0)
    fake_client.articles = [
        {"id": 1, "sourceId": 10, "sourceName": "源A", "title": "竞品发布企业 AI 助手新品", "content": "发布并公布新功能。", "url": "https://a/1", "collectedAt": base.isoformat(), "embedding": []},
        {"id": 2, "sourceId": 10, "sourceName": "源A", "title": "竞品发布 AI 助手新品", "content": "发布并公布新功能。", "url": "https://a/2", "collectedAt": (base + timedelta(minutes=1)).isoformat(), "embedding": []},
        {"id": 3, "sourceId": 11, "sourceName": "源B", "title": "某园区召开年度招商大会", "content": "数十家企业签约入驻。", "url": "https://b/3", "collectedAt": base.isoformat(), "embedding": []},
    ]
    clusters = rebuild_clusters(since_days=30)
    assert len(clusters) >= 2
    assert fake_client.replaced_clusters is clusters


def test_run_collection_task_success(fake_client):
    source = {"id": 10, "name": "源A", "type": "rss", "url": "https://a/feed", "frequency": "daily", "keywords": [], "competitors": [], "status": "enabled"}
    fake_client.sources[10] = dict(source)
    fake_client.tasks[1] = {"id": 1, "sourceId": 10, "status": "queued"}

    import app.services.intelligence as module

    def fake_collect(src):
        return [{"title": "T", "content": "C", "url": "https://a/x"}]

    module.collect_source = fake_collect
    task = run_collection_task(1)

    assert task is not None
    assert 1 in fake_client.started
    assert fake_client.resulted == [(1, 1)]
    healthy = [s for sid, s in fake_client.updated_run_states if sid == 10 and s.get("healthStatus") == "healthy"]
    assert healthy


def test_run_collection_task_marks_failure_and_raises(fake_client):
    source = {"id": 10, "name": "源A", "type": "web", "url": "https://a", "status": "enabled", "consecutiveFailures": 0}
    fake_client.sources[10] = dict(source)
    fake_client.tasks[1] = {"id": 1, "sourceId": 10, "status": "queued"}

    import app.services.intelligence as module

    def boom(src):
        raise RuntimeError("network down")

    module.collect_source = boom
    with pytest.raises(svc.CollectionRunError):
        run_collection_task(1)

    assert fake_client.failed and fake_client.failed[0][0] == 1
    degraded = [s for sid, s in fake_client.updated_run_states if sid == 10 and s.get("healthStatus") == "degraded"]
    assert degraded
