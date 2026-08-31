from app.meeting.generation import extract_insights, generate_cards, generate_report
from app.meeting.parsers import parse_transcript


def test_transcript_groups_speakers_and_locations():
    result = parse_transcript("张教授：行业将进入规模化阶段。\n\n主持人：下一步推进标准制定。")
    assert result["hasSpeakers"] is True
    assert result["segments"][0]["speaker"] == "张教授"
    assert result["segments"][0]["location"] == "第1段"


def test_rule_generation_keeps_traceable_sources(monkeypatch):
    class MockLLM:
        is_mock = True

    monkeypatch.setattr("app.meeting.generation.LLMClient", MockLLM)
    materials = [{
        "id": 7,
        "title": "转录稿",
        "parseStatus": "parsed",
        "parseResult": {
            "segments": [{
                "speaker": "王专家",
                "location": "第1段",
                "text": "未来一年将推进统一行业标准，并计划在2027年完成首批试点。",
            }]
        },
    }]
    insights = extract_insights(materials)
    assert insights
    assert insights[0]["sourceRef"][0]["materialId"] == 7
    cards = generate_cards(insights, [])
    assert all(card["sourceRef"] for card in cards)
    report, model = generate_report({"name": "行业论坛"}, insights, [])
    assert "[资料#7 第1段]" in report
    assert model == "rule-based"


def test_cards_without_source_are_marked_pending():
    cards = generate_cards([], [{
        "cardType": "核心观点",
        "title": "无来源观点",
        "content": "需要复核",
        "sourceRef": [],
    }])
    assert cards[0]["content"].startswith("【待确认】")
    assert cards[0]["sourceRef"][0]["status"] == "待确认"
