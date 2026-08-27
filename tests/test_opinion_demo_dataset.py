"""舆情演示数据验收用例。"""
from datetime import datetime

from app.opinion.analysis import rule_classify
from app.opinion.demo_data import DEMO_MONITOR, DEMO_RESPONSE_CASES, build_demo_articles


def test_demo_monitor_contains_matching_brand_word():
    assert DEMO_MONITOR["enterpriseName"] in DEMO_MONITOR["brandWords"]


def test_demo_articles_cover_three_sentiments_and_duplicate_topic():
    articles = build_demo_articles("pytest", datetime(2026, 8, 26, 12, 0, 0))
    results = [
        rule_classify(item["title"], item["content"], DEMO_MONITOR["brandWords"])
        for item in articles
    ]

    assert [item["sentiment"] for item in results].count("negative") == 2
    assert [item["sentiment"] for item in results].count("positive") == 1
    assert [item["sentiment"] for item in results].count("neutral") == 1
    assert results[0]["topic"] == results[1]["topic"]
    assert results[0]["risk_score"] >= 70


def test_demo_articles_have_unique_urls_and_cover_spread_markers():
    articles = build_demo_articles("pytest")
    assert len({item["url"] for item in articles}) == len(articles)
    assert "转载自" in articles[1]["content"]
    assert articles[0]["title"] in articles[1]["content"]


def test_demo_response_cases_cover_product_quality_alerts():
    assert len(DEMO_RESPONSE_CASES) >= 3
    quality_case = next(item for item in DEMO_RESPONSE_CASES if item["eventType"] == "产品质量投诉")
    assert quality_case["riskLevel"] == "预警"
    assert quality_case["strategy"]
    assert quality_case["content"]
