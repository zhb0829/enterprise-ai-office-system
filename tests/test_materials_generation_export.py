from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db import Base
from app.models import ReferenceMaterial

from app.routers.materials import _safe_upload_name
from app.services.export import UnsupportedExportFormat, _md_to_pdf, export_draft
from app.services.generation import load_materials_text, mock_generate_content
from app.services.materials import parse_material
from app.services.revise import revise_content


def test_safe_upload_name_strips_path_segments():
    assert _safe_upload_name("../bad/name?.txt") == "name_.txt"
    assert _safe_upload_name(r"..\bad\name?.txt") == "name_.txt"


def test_parse_txt_accepts_gb18030():
    assert parse_material("素材.txt", "中文内容".encode("gb18030")) == "中文内容"


def test_load_materials_text_accepts_string_ids():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ReferenceMaterial(id=7, filename="a.md", text_content="素材正文", status="已入库"))
        db.commit()
        assert "素材正文" in load_materials_text(db, ["7"])
    engine.dispose()


def test_mock_generation_includes_materials_summary():
    content = mock_generate_content(
        {"title": "标题", "eventDesc": "事件"},
        {"sections": [{"key": "body", "name": "正文", "hint": "说明"}]},
        [],
        "正式",
        "这是一段参考素材",
    )
    assert "参考素材摘要" in content


def test_revise_content_passes_materials_to_llm():
    class Llm:
        is_mock = False

        def chat(self, messages, model=None, temperature=None, **kwargs):
            assert "参考素材正文" in messages[1]["content"]
            # G4/G6：修订链路必须标注用途，成本才能按功能归集
            assert kwargs["purpose"] == "draft.revise"
            return "ok"

    base = SimpleNamespace(content="# 原稿")
    assert revise_content(base, "补充信息", Llm(), "参考素材正文") == "ok"


def test_export_filename_includes_draft_id(tmp_path, monkeypatch):
    class Db:
        def __init__(self):
            self.committed = False

        def get(self, model, draft_id):
            return SimpleNamespace(id=draft_id, title="同名标题", content="# 内容")

        def add(self, row):
            self.row = row

        def commit(self):
            self.committed = True

    monkeypatch.setattr("app.services.export.settings", SimpleNamespace(export_path=tmp_path))
    path, filename = export_draft(Db(), "draft_abc_v1", "md")

    assert filename == "同名标题_draft_abc_v1.md"
    assert path.endswith(filename)
    assert (tmp_path / filename).read_text(encoding="utf-8") == "# 内容"


def test_pdf_export_generates_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.export.settings",
        SimpleNamespace(export_path=tmp_path, pdf_chinese_font="C:/Windows/Fonts/msyh.ttc"),
    )
    out = tmp_path / "out.pdf"
    _md_to_pdf("# 通知标题\n\n- 时间：2026年9月18日\n\n正文内容", out)

    assert out.stat().st_size > 0


def test_pdf_export_without_chinese_font_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.export.settings",
        SimpleNamespace(export_path=tmp_path, pdf_chinese_font="不存在的字体.ttf"),
    )
    monkeypatch.setattr(
        "app.services.export._CJK_FONT_CANDIDATES", (),
    )
    with pytest.raises(UnsupportedExportFormat, match="中文字体"):
        _md_to_pdf("# 内容", tmp_path / "out.pdf")
