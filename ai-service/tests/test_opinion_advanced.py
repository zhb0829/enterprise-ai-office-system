"""P1 舆情 - 阶段5/6 Python 能力验证（报告/建议/传播）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.opinion.reports import _rule_report, export_pdf
from app.opinion.spread import analyze as analyze_spread
from app.opinion.rag import _chunk, _retrieve, _query_text
from app.opinion.spread import _simhash, _hamming


def test_rule_report_builds_html_and_summary():
    data = {
        "monitor": "某科技",
        "articleCount": 5,
        "sentiment": {"positive": 1, "neutral": 2, "negative": 2},
        "events": [{"title": "质量问题事件", "riskLevel": "预警", "reportCount": 3}],
        "alerts": [{"riskLevel": "预警", "state": "triggered"}],
        "evidence": [{"title": "示例文章", "url": "https://example.com/a"}],
    }
    summary, content_html, evidence = _rule_report(data, "daily", 1, "2026-08-24 00:00:00", "2026-08-25 00:00:00")
    assert "负面 2" in summary
    assert "<h3>" in content_html and "热点事件" in content_html
    assert any("example.com" in item for item in evidence)


def test_export_pdf_falls_back_to_html():
    result = export_pdf(1, "测试报告", "<h3>标题</h3><p>正文</p>")
    assert result["format"] in ("pdf", "html")
    assert result["downloadUrl"].startswith("/static/uploads/")


def test_simhash_distance_reflects_similarity():
    left = _simhash("某公司发布新一代企业 AI 助手")
    right = _simhash("某公司发布企业AI助手新版本")
    unrelated = _simhash("今日天气晴到多云")
    assert _hamming(left, right) < _hamming(left, unrelated)


def test_spread_analyze_returns_inferred_and_verified_edges():
    articles = [
        {"id": 1, "title": "某公司被曝质量问题", "content": "消费者投诉产品存在缺陷。", "url": "https://a.com/1",
         "sourceId": 1, "publishTime": "2026-08-24 08:00:00"},
        {"id": 2, "title": "某公司被曝质量问题（转载自某网）", "content": "本文转载自某网，消费者投诉产品存在缺陷。",
         "url": "https://b.com/2", "sourceId": 2, "publishTime": "2026-08-24 10:00:00"},
        {"id": 3, "title": "某公司发布年度财报", "content": "营收增长。", "url": "https://c.com/3",
         "sourceId": 3, "publishTime": "2026-08-24 09:00:00"},
        {"id": 4, "title": "某公司被曝质量问题后续", "content": "消费者继续投诉产品存在缺陷。",
         "url": "https://d.com/4", "sourceId": 4, "publishTime": "2026-08-24 11:00:00"},
    ]
    result = analyze_spread(10, articles)
    edges = result["edges"]
    verified = [e for e in edges if e["verified"]]
    inferred = [e for e in edges if not e["verified"]]
    assert any(e["relationType"] == "转载" for e in verified)
    assert any(e["relationType"] == "相似" for e in inferred)
    for edge in edges:
        assert edge["fromArticleId"] != edge["toArticleId"]
        assert edge["fromArticleId"] < edge["toArticleId"]


def test_spread_analyze_keeps_one_nearest_inferred_parent_per_article():
    articles = [
        {"id": 1, "title": "产品质量问题持续发酵", "content": "消费者投诉产品存在质量缺陷。",
         "publishTime": "2026-08-24 08:00:00"},
        {"id": 2, "title": "产品质量问题持续发酵", "content": "消费者投诉产品存在质量缺陷。",
         "publishTime": "2026-08-24 09:00:00"},
        {"id": 3, "title": "产品质量问题持续发酵", "content": "消费者投诉产品存在质量缺陷。",
         "publishTime": "2026-08-24 10:00:00"},
    ]
    edges = analyze_spread(10, articles)["edges"]
    incoming = [edge for edge in edges if edge["toArticleId"] == 3]
    assert len(incoming) == 1
    assert incoming[0]["fromArticleId"] == 2


def test_rag_chunking_and_query_text():
    text = "策略：先核实事实并公开回应。优先保护消费者权益并留存证据。" * 60
    chunks = _chunk(text)
    assert len(chunks) >= 2
    assert all(len(c) <= 800 for c in chunks)
    query = _query_text({"monitorName": "某科技", "title": "质量事件", "summary": "负面舆情", "riskLevel": "预警"})
    assert "某科技" in query


def test_rag_retrieve_empty_when_no_index(monkeypatch):
    class EmptyQuery:
        def order_by(self, _field):
            return self

        def all(self):
            return []

    class Empty:
        def query(self, _model):
            return EmptyQuery()

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_db(*args, **kwargs):
        return Empty()

    monkeypatch.setattr("app.opinion.rag.SessionLocal", fake_db)
    assert _retrieve("质量问题") == []
