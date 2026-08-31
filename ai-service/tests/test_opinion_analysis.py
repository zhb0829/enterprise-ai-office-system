"""P1 舆情 - Python AI 能力验证（结构化输出 / 标注集 / 脱敏 / 去重）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.opinion.analysis import (
    rule_classify,
    sanitize_sensitive,
    _should_deepseek,
    analyze_article,
)
from app.opinion.adapters import content_hash, url_hash, dedupe, normalize_url


def test_rule_classify_negative_risk_article():
    result = rule_classify(
        "XX 公司因质量问题被曝光并面临诉讼",
        "多位消费者投诉产品质量问题，监管部门已立案调查。",
        ["XX公司"],
    )
    assert result["sentiment"] == "negative"
    assert 0 <= result["confidence"] <= 1
    assert result["risk_score"] >= 40
    assert "risk" not in result
    for key in ("sentiment", "confidence", "emotion_tags", "reason", "evidence", "risk_factors",
                "risk_score", "topic", "keywords", "model", "prompt_version"):
        assert key in result


def test_rule_classify_positive_article():
    result = rule_classify(
        "XX 公司营收增长突破历史新高",
        "本季度营收同比增长 30%，新产品获得市场好评。",
        [],
    )
    assert result["sentiment"] == "positive"


def test_rule_classify_neutral_article():
    result = rule_classify(
        "XX 公司召开年度战略发布会",
        "公司发布了未来一年的战略方向与业务布局规划。",
        [],
    )
    assert result["sentiment"] == "neutral"


def test_should_deepseek_flags_low_confidence_neutral():
    result = rule_classify("XX 公司发布声明", "公司就相关传闻作出说明。", [])
    assert _should_deepseek(result)


def test_sanitize_sensitive_masks_pii():
    text = "联系电话 13812345678，邮箱 a@b.com，身份证 110101199001011234"
    masked = sanitize_sensitive(text)
    assert "13812345678" not in masked
    assert "a@b.com" not in masked


def test_content_hash_is_stable_and_url_normalized():
    a = content_hash("行业趋势", "正文内容", "https://EXAMPLE.com/path/?utm_source=x")
    b = content_hash("行业趋势", "正文内容", "https://example.com/path")
    assert a == b
    assert url_hash("https://Example.com/Path") == url_hash("https://example.com/Path")


def test_dedupe_keeps_first_occurrence():
    items = [
        {"content_hash": "h1", "title": "A"},
        {"content_hash": "h1", "title": "A(重复)"},
        {"content_hash": "h2", "title": "B"},
    ]
    result = dedupe(items)
    assert len(result) == 2


def test_analyze_article_returns_structured_payload(monkeypatch):
    monkeypatch.setattr("app.opinion.analysis._record_model_call", lambda *a, **k: None)
    payload = analyze_article({
        "taskId": 1,
        "articleId": 2,
        "monitorId": 3,
        "title": "XX 公司被曝质量问题",
        "content": "消费者投诉产品存在重大质量缺陷。",
        "url": "https://example.com/x",
        "matchedKeywords": ["XX公司"],
    })
    assert payload["sentiment"] == "negative"
    assert "taskId" in payload and "aiRunId" in payload and "evidenceIds" in payload


def test_parse_source_url_normalization():
    assert normalize_url("http://Example.com/a///") == "http://example.com/a"
