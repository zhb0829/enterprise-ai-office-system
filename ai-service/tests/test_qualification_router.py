from app.routers.qualification import _build_guide_schema, _build_material_checklist


def test_build_guide_schema_detects_numbered_sections():
    schema = _build_guide_schema("一、申报条件\n（一）人员要求\n二、申报材料")

    assert [section["title"] for section in schema["sections"]] == [
        "一、申报条件",
        "（一）人员要求",
        "二、申报材料",
    ]


def test_build_guide_schema_ignores_numbered_requirements():
    schema = _build_guide_schema(
        "一、申报条件\n"
        "1. 企业应依法注册并持续经营满一年。\n"
        "2. 企业应建立服务制度。\n"
        "二、申报材料\n"
        "1. 营业执照复印件"
    )

    assert [section["title"] for section in schema["sections"]] == ["一、申报条件", "二、申报材料"]


def test_build_guide_schema_detects_hierarchical_standard_headings():
    schema = _build_guide_schema("3.1 术语和定义 1…………\n3.1.1 服务能力\n表 1 服务类型\n4.1 成熟度级别")

    assert [section["title"] for section in schema["sections"]] == ["3.1 术语和定义", "3.1.1 服务能力", "4.1 成熟度级别"]


def test_build_material_checklist_extracts_material_lines():
    checklist = _build_material_checklist("营业执照复印件\n研发费用专项审计报告\n这是一段普通说明")

    assert [item["name"] for item in checklist] == ["营业执照复印件", "研发费用专项审计报告"]
