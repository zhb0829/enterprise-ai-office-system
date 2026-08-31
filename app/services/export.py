"""导出服务：草稿导出为 Markdown / DOCX / PDF。

PDF 导出使用 reportlab（纯 Python），中文字体自动探测本机字体，
可通过 PDF_CHINESE_FONT 指定首选字体文件路径。
"""
import logging
import re
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Draft, ExportLog

logger = logging.getLogger(__name__)


class UnsupportedExportFormat(Exception):
    pass


def export_draft(db: Session, draft_id: str, fmt: str) -> tuple[str, str]:
    """导出草稿，返回 (文件路径, 文件名)。"""
    draft = db.get(Draft, draft_id)
    if not draft:
        raise FileNotFoundError(f"草稿不存在: {draft_id}")

    safe_title = re.sub(r'[\\/:*?"<>|]', "_", draft.title or draft.id)[:60] or "draft"
    filename = f"{safe_title}_{draft.id}.{fmt}"
    path = settings.export_path / filename

    if fmt == "md":
        path.write_text(draft.content, encoding="utf-8")
    elif fmt == "docx":
        _md_to_docx(draft.content, str(path))
    elif fmt == "pdf":
        _md_to_pdf(draft.content, path)
    else:
        raise UnsupportedExportFormat(f"不支持的导出格式: {fmt}")

    db.add(ExportLog(draft_id=draft_id, format=fmt, file_path=str(path)))
    db.commit()
    logger.info("导出成功: draft=%s fmt=%s path=%s", draft_id, fmt, path)
    return str(path), filename


def _clean_md(text: str) -> str:
    """去除 Markdown 强调符号，便于 DOCX 显示。"""
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.replace("**", "").replace("__", "").replace("~~", "").replace("*", "")


def _md_to_docx(md: str, path: str) -> None:
    """将 Markdown 草稿简单转换为 DOCX（标题/列表/段落）。"""
    from docx import Document
    from docx.oxml.ns import qn

    doc = Document()
    # 中文默认字体（改善 DOCX 中文显示）
    normal = doc.styles["Normal"]
    normal.font.name = "SimSun"
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    for style_name in ("Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[style_name]
        style.font.name = "SimSun"
        style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    in_code = False
    for line in md.splitlines():
        s = line.rstrip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if not s:
            doc.add_paragraph("")
            continue
        text = s if in_code else _clean_md(s)
        if s.startswith("### "):
            doc.add_heading(text[4:], level=3)
        elif s.startswith("## "):
            doc.add_heading(text[3:], level=2)
        elif s.startswith("# "):
            doc.add_heading(text[2:], level=1)
        elif s.startswith("- "):
            doc.add_paragraph(text[2:], style="List Bullet")
        elif re.match(r"^\d+\.\s+", s):
            doc.add_paragraph(re.sub(r"^\d+\.\s+", "", text), style="List Number")
        elif s.startswith("> "):
            doc.add_paragraph(text[2:], style="Intense Quote")
        elif "|" in s and s.strip().startswith("|"):
            doc.add_paragraph(" ".join(part.strip() for part in text.strip("|").split("|") if part.strip()))
        else:
            doc.add_paragraph(text)
    doc.save(path)


def _md_to_pdf(md: str, path: Path) -> None:
    """将 Markdown 草稿转换为 PDF（reportlab，支持中文）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font_name = _register_chinese_font(pdfmetrics, TTFont)
    if not font_name:
        raise UnsupportedExportFormat("未找到可用中文字体，PDF 导出失败；可通过 PDF_CHINESE_FONT 指定字体文件路径")

    body = ParagraphStyle(
        "Body", fontName=font_name, fontSize=10.5, leading=18, spaceAfter=6, firstLineIndent=0
    )
    heading = ParagraphStyle(
        "Heading", parent=body, fontSize=15, leading=22, spaceBefore=10, spaceAfter=8
    )
    subheading = ParagraphStyle(
        "SubHeading", parent=body, fontSize=13, leading=20, spaceBefore=8, spaceAfter=6
    )
    subsubheading = ParagraphStyle(
        "SubSubHeading", parent=body, fontSize=11.5, leading=18, spaceBefore=6, spaceAfter=5
    )
    quote = ParagraphStyle(
        "Quote", parent=body, leftIndent=8 * mm, textColor="#444444"
    )
    bullet = ParagraphStyle("Bullet", parent=body, leftIndent=6 * mm, bulletIndent=2 * mm)
    numbered = ParagraphStyle("Numbered", parent=body, leftIndent=6 * mm)

    def esc(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=25 * mm,
        rightMargin=25 * mm,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        title="",
    )
    story: list = []
    in_code = False
    for line in md.splitlines():
        s = line.rstrip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if not s:
            story.append(Spacer(1, 6))
            continue
        text = esc(s if in_code else _clean_md(s))
        if s.startswith("### "):
            story.append(Paragraph(text[4:], subsubheading))
        elif s.startswith("## "):
            story.append(Paragraph(text[3:], subheading))
        elif s.startswith("# "):
            story.append(Paragraph(text[2:], heading))
        elif s.startswith("- "):
            story.append(Paragraph(text[2:], bullet, bulletText="•"))
        elif re.match(r"^\d+\.\s+", s):
            story.append(Paragraph(text, numbered))
        elif s.startswith("> "):
            story.append(Paragraph(text[2:], quote))
        else:
            story.append(Paragraph(text, body))
    doc.build(story)


# reportlab 对 .ttc 字体集合仅取第一个子字体，常规中文字体均可用
_CJK_FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)


def _register_chinese_font(pdfmetrics, ttfont_cls) -> str:
    """注册本机中文字体，返回字体名；找不到返回空串。"""
    configured = settings.pdf_chinese_font
    candidates: list[Path] = []
    if Path(configured).suffix.lower() in (".ttf", ".ttc", ".otf"):
        candidates.append(Path(configured))
    candidates.extend(Path(p) for p in _CJK_FONT_CANDIDATES)
    for candidate in candidates:
        if not candidate:
            continue
        if not candidate.is_file():
            continue
        name = f"EaosCJK-{candidate.stem}"
        try:
            pdfmetrics.registerFont(ttfont_cls(name, str(candidate), subfontIndex=0))
            return name
        except Exception as exc:  # 字体文件损坏或不兼容时继续尝试下一个
            logger.warning("注册中文字体失败: %s (%s)", candidate, exc)
    return ""
