"""素材解析：md/txt/docx/pdf 文本提取。"""
from io import BytesIO

SUPPORTED_EXTS = {"md", "txt", "docx", "pdf"}


class UnsupportedFileError(Exception):
    pass


class MaterialParseError(Exception):
    pass


def parse_material(filename: str, data: bytes) -> str:
    """解析上传文件为纯文本。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    try:
        if ext in ("md", "txt"):
            return _decode_text(data)
        if ext == "docx":
            return _ensure_text(_parse_docx(data), "DOCX 未提取到可用文本")
        if ext == "pdf":
            return _ensure_text(_parse_pdf(data), "PDF 未提取到可用文本，可能是扫描件或加密文件")
    except MaterialParseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MaterialParseError(f"素材解析失败: {exc}") from exc
    raise UnsupportedFileError(f"不支持的文件格式: .{ext}，仅支持 md/txt/docx/pdf")


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise MaterialParseError("文本编码不支持，请使用 UTF-8 或 GB18030 编码")


def _ensure_text(text: str, message: str) -> str:
    text = text.strip()
    if not text:
        raise MaterialParseError(message)
    return text


def _parse_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    table_rows = []
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                table_rows.append(" | ".join(cells))
    return "\n".join([*paragraphs, *table_rows])


def _parse_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)
