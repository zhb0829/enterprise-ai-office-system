from app.services.qualification import build_document


def test_build_document_uses_guide_sections_and_traceable_sources():
    document, sources, risk_flags = build_document(
        {
            "qualificationType": "IT 服务能力",
            "documentType": "标准编制任务",
            "guide": {
                "id": "guide-1",
                "guideName": "IT 服务能力标准",
                "version": "2026-v1",
                "schema": {"sections": [{"key": "requirements", "title": "一、申报条件"}]},
            },
            "materials": [{"id": "material-1", "fileName": "营业执照.txt", "text": "企业成立于 2020 年。"}],
        }
    )

    assert document["title"] == "IT 服务能力标准编制任务"
    assert document["sections"][0]["title"] == "一、申报条件"
    assert document["sections"][0]["blocks"][0]["citations"] == [{"id": "guide:guide-1"}, {"id": "material:material-1"}]
    assert [source["id"] for source in sources] == ["guide:guide-1", "material:material-1"]
    assert risk_flags == []
