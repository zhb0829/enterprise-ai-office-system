"""素材解析、分块、语义向量化与引用检索。"""
from __future__ import annotations

import hashlib
import logging
import math
import re
from dataclasses import dataclass
from io import BytesIO

from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
from sqlalchemy.orm import Session

from ..config import settings
from ..agent.runtime_flags import disabled as flag_disabled
from ..models import MaterialChunk, ReferenceMaterial
from . import capacity, cost

SUPPORTED_EXTS = {"md", "txt", "docx", "pdf"}
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120
SEMANTIC_MIN_SIZE = 320
SEMANTIC_SIMILARITY_THRESHOLD = 0.42
CHUNKING_VERSION = "hybrid-v1"
EMBEDDING_DIMS = 64

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextChunk:
    """A retrieval chunk and its source-level metadata."""

    text: str
    parent_index: int
    split_method: str
    start: int
    end: int
    parent_text: str


class UnsupportedFileError(Exception):
    pass


class MaterialParseError(Exception):
    pass


class EmbeddingError(Exception):
    pass


class EmbeddingClient:
    """通过 OpenAI 兼容接口生成语义向量。"""

    def __init__(self):
        self.is_configured = bool(settings.embedding_api_key and settings.embedding_model)
        self._client = None
        if self.is_configured:
            self._client = OpenAI(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
                timeout=settings.embedding_timeout,
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.is_configured:
            raise EmbeddingError("未配置 EMBEDDING_API_KEY 或 EMBEDDING_MODEL")
        try:
            from ..agent.governance import model_messages
            texts = [item["content"] for item in model_messages([{"content": text} for text in texts])]
            request = {"model": settings.embedding_model, "input": texts}
            if settings.embedding_dimensions:
                request["dimensions"] = settings.embedding_dimensions
            # 向量化是耗时的外部链路：容量池满时快速失败，不无限排队。
            response = capacity.run("embedding", self._client.embeddings.create, **request)
        except capacity.CapacityError as exc:
            logger.warning("向量化容量池已满，已快速失败: %s", exc)
            raise EmbeddingError(f"向量化并发配额已满，已快速失败：{exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"Embedding 服务调用失败：{exc}") from exc

        # G6：向量模型用量也进成本口径；供应商不回 usage 时只记次数，成本记 null
        usage = getattr(response, "usage", None)
        cost.record_usage(
            model=settings.embedding_model, purpose="embedding",
            input_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
            output_tokens=0, tokens_available=usage is not None,
        )

        vectors = [[] for _ in texts]
        for item in response.data:
            if 0 <= item.index < len(vectors):
                vectors[item.index] = [float(value) for value in item.embedding]
        if any(not vector for vector in vectors):
            raise EmbeddingError("Embedding 服务返回的向量数量不完整")
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) != 1:
            raise EmbeddingError("Embedding 服务返回的向量维度不一致")
        expected_dimensions = settings.embedding_dimensions
        actual_dimensions = next(iter(dimensions))
        if expected_dimensions and actual_dimensions != expected_dimensions:
            raise EmbeddingError(
                f"Embedding 维度不符合配置：期望 {expected_dimensions}，实际 {actual_dimensions}"
            )
        return vectors


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
    from docx.table import Table

    doc = Document(BytesIO(data))
    blocks = []
    for block in doc.iter_inner_content():
        if isinstance(block, Table):
            rows = [
                "| " + " | ".join(cell.text.strip().replace("\n", " ") for cell in row.cells) + " |"
                for row in block.rows
            ]
            if rows:
                blocks.append("\n".join(rows))
        elif block.text.strip():
            blocks.append(block.text.strip())
    return "\n\n".join(blocks)


def _parse_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)


def _normalize_text(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text or "").strip()
    return re.sub(r"[ \t]+\n", "\n", text)


def _recursive_text_chunks(
    text: str,
    *,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[TextChunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", ". ", "! ", "? ", "; ", "，", ", ", " ", ""],
        keep_separator="end",
        add_start_index=True,
    )
    return [
        TextChunk(
            doc.page_content, 0, "recursive", doc.metadata["start_index"],
            doc.metadata["start_index"] + len(doc.page_content), text,
        )
        for doc in splitter.create_documents([text])
    ]


_HEADING_RE = re.compile(
    r"(?m)^(?:#{1,6}\s+\S.*|第[一二三四五六七八九十百千万零〇\d]+章[^\n]*"
    r"|[一二三四五六七八九十百千万零〇\d]+、[^\n]{1,80})$"
)
_LIST_RE = re.compile(r"(?m)^\s*(?:[-*+]\s+|\d+[.)、]\s*|[（(][一二三四五六七八九十\d]+[）)])")


def _structural_spans(text: str, target: int) -> list[tuple[int, int]]:
    fences = list(re.finditer(r"(?ms)^(```|~~~)[^\n]*\n.*?^\1[ \t]*(?=\n|$)", text))
    if fences:
        spans = []
        cursor = 0
        for fence in fences:
            spans.extend((cursor + start, cursor + end) for start, end in _structural_spans(text[cursor:fence.start()], target))
            spans.append((fence.start(), fence.end()))
            cursor = fence.end()
        spans.extend((cursor + start, cursor + end) for start, end in _structural_spans(text[cursor:], target))
        return spans
    sections = sorted({0, len(text), *(match.start() for match in _HEADING_RE.finditer(text))})
    spans = []
    for start, end in zip(sections, sections[1:]):
        section = text[start:end]
        if len(section.strip()) <= target:
            spans.append((start, end))
            continue
        boundaries = [start, *(start + m.end() for m in re.finditer(r"\n[ \t]*\n+", section)), end]
        # Keep a heading with its first paragraph.
        if len(boundaries) > 2 and _HEADING_RE.fullmatch(text[start:boundaries[1]].strip()):
            boundaries.pop(1)
        spans.extend(zip(boundaries, boundaries[1:]))
    return spans


def _protected_block(text: str) -> bool:
    return bool(re.search(r"(?m)^\s*\|.*\|", text)) or bool(_LIST_RE.search(text)) or text.lstrip().startswith(("```", "~~~"))


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    boundaries = [0, *(m.end() for m in re.finditer(r"[。！？；]|[.!?;](?=\s|$)", text)), len(text)]
    return [(start, end) for start, end in zip(boundaries, boundaries[1:]) if text[start:end].strip()]


def _semantic_split_chunk(
    chunk: TextChunk,
    *,
    embedder,
    min_size: int = SEMANTIC_MIN_SIZE,
    max_size: int = CHUNK_SIZE,
    threshold: float = SEMANTIC_SIMILARITY_THRESHOLD,
) -> list[TextChunk]:
    """Split a long recursive chunk at sentence-topic boundaries."""
    spans = _sentence_spans(chunk.text)
    if len(spans) < 3:
        return [chunk]
    vectors = embedder([chunk.text[start:end].strip() for start, end in spans])
    if len(vectors) != len(spans):
        return [chunk]
    if (
        not vectors or not vectors[0] or len({len(v) for v in vectors}) != 1
        or any(not all(math.isfinite(value) for value in v) or not any(v) for v in vectors)
    ):
        return [chunk]
    boundaries = [0]
    for index in range(1, len(spans)):
        boundary = spans[index][0]
        length = boundary - boundaries[-1]
        tail = len(chunk.text) - boundary
        similarity = _cosine(vectors[index - 1], vectors[index])
        if (
            length >= min_size and tail >= min_size
            and (similarity < threshold or length + spans[index][1] - boundary > max_size)
        ):
            boundaries.append(boundary)
    boundaries.append(len(chunk.text))
    if len(boundaries) == 2:
        return [chunk]
    return [
        TextChunk(
            chunk.text[start:end], chunk.parent_index, "semantic",
            chunk.start + start, chunk.start + end, chunk.parent_text,
        )
        for start, end in zip(boundaries, boundaries[1:])
    ]


def split_text_chunks(
    text: str,
    *,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    semantic: bool = True,
    embedder=None,
    preserve_parent: bool = False,
) -> list[TextChunk]:
    """Recursive-first splitting with optional semantic refinement for long chunks."""
    normalized = _normalize_text(text)
    if not normalized:
        return []
    if chunk_size <= 0 or not 0 <= overlap < chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller than chunk_size")
    parent_spans = [(0, len(normalized))] if preserve_parent else _structural_spans(normalized, chunk_size)
    refined: list[TextChunk] = []
    for parent_index, (start, end) in enumerate(parent_spans):
        raw = normalized[start:end]
        start += len(raw) - len(raw.lstrip())
        parent = raw.strip()
        if not parent:
            continue
        root = TextChunk(parent, parent_index, "structure", start, start + len(parent), parent)
        if len(parent) <= chunk_size or _protected_block(parent):
            refined.append(root)
            continue
        sections = [root]
        if semantic and embedder is not None and len(parent) >= settings.chunk_semantic_trigger_size:
            try:
                sections = _semantic_split_chunk(
                    root, embedder=embedder,
                    min_size=min(settings.chunk_min_size, chunk_size),
                    max_size=chunk_size, threshold=settings.chunk_semantic_similarity_threshold,
                )
            except (EmbeddingError, ValueError, TypeError):
                sections = [root]
        for section in sections:
            children = _recursive_text_chunks(section.text, chunk_size=chunk_size, overlap=overlap)
            for child in children:
                refined.append(TextChunk(
                    child.text, parent_index,
                    "semantic" if section.split_method == "semantic" else "recursive",
                    section.start + child.start, section.start + child.end, parent,
                ))
    return refined


def chunk_metadata(chunk: TextChunk) -> dict:
    return {
        "chunking_version": CHUNKING_VERSION,
        "split_method": chunk.split_method,
        "parent_chunk_index": chunk.parent_index,
        "parent_text": chunk.parent_text,
        "source_start": chunk.start,
        "source_end": chunk.end,
    }


def split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Compatibility entry point: deterministic recursive splitting only."""
    return [chunk.text for chunk in split_text_chunks(text, chunk_size=chunk_size, overlap=overlap, semantic=False)]


def _hash_embed(text: str) -> list[float]:
    """离线开发兜底，不作为配置真实 Embedding 后的生产索引。"""
    vector = [0.0] * EMBEDDING_DIMS
    tokens = re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z0-9_.%-]+", text.lower())
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "big") % EMBEDDING_DIMS
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[idx] += sign
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [round(v / norm, 6) for v in vector]


def embedding_info(vector: list[float] | None = None) -> dict:
    if settings.embedding_api_key and settings.embedding_model:
        return {
            "embedding_backend": "remote",
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": len(vector or []),
        }
    return {
        "embedding_backend": "hash-fallback",
        "embedding_model": f"hash-{EMBEDDING_DIMS}",
        "embedding_dimensions": EMBEDDING_DIMS,
    }


def embed_texts(texts: list[str], client: EmbeddingClient | None = None) -> list[list[float]]:
    """批量生成向量；配置真实服务后，远端异常会显式失败而非混入哈希向量。"""
    values = [(text or "").strip() for text in texts]
    if not values:
        return []
    if any(not value for value in values):
        raise EmbeddingError("待向量化文本不能为空")

    client = client or EmbeddingClient()
    if client.is_configured and flag_disabled("remote_embedding"):
        # 关闭远程向量开关后不得用哈希向量顶替：库里存的是真实向量，混用会让相似度口径失真。
        raise EmbeddingError(
            "运行时开关 remote_embedding 已关闭，拒绝以哈希向量顶替真实向量"
        )
    if not client.is_configured:
        return [_hash_embed(value) for value in values]

    batch_size = max(1, min(settings.embedding_batch_size, 2048))
    vectors: list[list[float]] = []
    for start in range(0, len(values), batch_size):
        vectors.extend(client.embed(values[start : start + batch_size]))
    return vectors


def embed_text(text: str) -> list[float]:
    """单文本兼容入口。新代码优先在入库时调用 embed_texts 批量请求。"""
    return embed_texts([text])[0]


def _embedding_meta(existing: dict | None, vector: list[float]) -> dict:
    return {**(existing or {}), **embedding_info(vector)}


def embedding_is_compatible(meta: dict | None, query_vector: list[float]) -> bool:
    meta = meta or {}
    backend = meta.get("embedding_backend")
    dimensions = int(meta.get("embedding_dimensions") or 0)
    if settings.embedding_api_key and settings.embedding_model:
        return (
            backend == "remote"
            and meta.get("embedding_model") == settings.embedding_model
            and dimensions == len(query_vector)
        )
    return (
        (backend == "hash-fallback" or not backend)
        and (not dimensions or dimensions == len(query_vector))
    )


def build_material_chunks(db: Session, material: ReferenceMaterial) -> int:
    """为素材生成分块与向量，返回分块数量。"""
    db.query(MaterialChunk).filter(MaterialChunk.material_id == material.id).delete()
    from ..agent.governance import classified_data
    with classified_data(material.classification):
        semantic_embedder = (
            embed_texts if settings.chunk_semantic_enabled and settings.embedding_api_key and settings.embedding_model
            else None
        )
        chunks = split_text_chunks(material.text_content, semantic=True, embedder=semantic_embedder)
        texts = [chunk.text for chunk in chunks]
        vectors = embed_texts(texts)
    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
        db.add(
            MaterialChunk(
                material_id=material.id,
                chunk_index=index,
                text=chunk.text,
                embedding=vector,
                meta=_embedding_meta(
                    {
                        "filename": material.filename,
                        "text_length": len(chunk.text),
                        **chunk_metadata(chunk),
                    },
                    vector,
                ),
            )
        )
    material.status = "已入库"
    db.expire(material, ["chunks"])
    db.flush()
    sync_material_document(db, material)
    return len(chunks)


def sync_material_document(db, material):
    from ..agent.knowledge import KnowledgeStore, namespace_for
    from ..agent.governance import Principal, principal_var
    from fastapi import HTTPException
    p = principal_var.get()
    if p.authenticated and not p.can_read(
        material.classification, material.tenant_id, material.department_id, material.owner_id,
    ):
        raise HTTPException(403, "material is outside the trusted data scope")
    store = KnowledgeStore(db, namespace_for("materials"))
    if not store.active():
        # Bootstrap the complete tenant manifest, including other owners. Visibility
        # remains enforced when a snapshot is read, not when history is preserved.
        token = principal_var.set(Principal())
        try:
            materials = db.query(ReferenceMaterial).filter(
                ReferenceMaterial.tenant_id == material.tenant_id,
                ReferenceMaterial.status.like("已入库%"),
            ).all()
            documents = [_material_manifest(db, item) for item in materials]
            row = store.stage(documents)
        finally:
            principal_var.reset(token)
    else:
        row = store.stage([_material_manifest(db, material)])
    if row.changes["added"] or row.changes["updated"]:
        store.publish(row.id)
    else:
        store.discard(row)
    return row


def _material_manifest(db, material):
    rows = db.query(MaterialChunk).filter_by(material_id=material.id).order_by(MaterialChunk.chunk_index).all()
    return {
        "key": f"material:{material.id}", "classification": material.classification,
        "tenant_id": material.tenant_id, "department_id": material.department_id, "owner_id": material.owner_id,
        "metadata": {"materialId": material.id, "filename": material.filename},
        "chunks": [{"id": r.id, "text": r.text, "embedding": r.embedding, "meta": r.meta} for r in rows],
    }


def reindex_material_embeddings(db: Session, material_id: int | None = None, *, rechunk: bool = False) -> dict:
    if rechunk:
        query = db.query(ReferenceMaterial).filter(ReferenceMaterial.status.like("已入库%"))
        if material_id is not None:
            query = query.filter(ReferenceMaterial.id == material_id)
        materials = query.order_by(ReferenceMaterial.id).all()
        count = sum(build_material_chunks(db, material) for material in materials)
        first = db.query(MaterialChunk).filter(
            MaterialChunk.material_id.in_([material.id for material in materials])
        ).first() if materials else None
        info = embedding_info(first.embedding if first else None)
        db.commit()
        return {"materials": len(materials), "chunks": count, **info}
    query = db.query(MaterialChunk).join(ReferenceMaterial)
    if material_id is not None:
        query = query.filter(MaterialChunk.material_id == material_id)
    chunks = query.order_by(MaterialChunk.id).all()
    from ..agent.governance import classified_data
    vectors = []
    for chunk in chunks:
        material = db.query(ReferenceMaterial).filter_by(id=chunk.material_id).one()
        with classified_data(material.classification):
            vectors.extend(embed_texts([chunk.text]))
    material_ids: set[int] = set()
    for chunk, vector in zip(chunks, vectors):
        chunk.embedding = vector
        chunk.meta = _embedding_meta(chunk.meta, vector)
        material_ids.add(chunk.material_id)
    db.flush()
    for mid in material_ids:
        sync_material_document(db, db.get(ReferenceMaterial, mid))
    db.commit()
    return {
        "materials": len(material_ids),
        "chunks": len(chunks),
        **embedding_info(vectors[0] if vectors else None),
    }


def search_material_chunks(
    db: Session,
    query: str,
    material_ids: list[int] | None = None,
    limit: int = 6,
) -> list[dict]:
    """引用检索：关键词分数 + 语义向量余弦相似度，返回可引用片段。"""
    query = (query or "").strip()
    if not query:
        return []
    limit = max(1, min(limit, 20))
    from ..agent.knowledge import KnowledgeStore, namespace_for
    from ..agent.governance import DataLevel, data_level_var
    snapshot = KnowledgeStore(db, namespace_for("materials")).snapshot()
    if snapshot["releaseId"]:
        rows = []
        from types import SimpleNamespace
        for entry in snapshot["entries"]:
            metadata = entry["metadata_"]
            mid = metadata.get("materialId")
            if material_ids and mid not in material_ids:
                continue
            for index, chunk in enumerate(entry["chunks"]):
                rows.append((SimpleNamespace(
                    id=chunk.get("id") or -int(entry["content_hash"][:12], 16) - index,
                    material_id=mid or 0, chunk_index=index, text=chunk["text"],
                    embedding=chunk.get("embedding", []), meta=chunk.get("meta", {}),
                    created_at=None,
                ), metadata.get("filename", entry["key"]), entry["classification"]))
    else:
        rows = _legacy_material_rows(db, material_ids)
    if not rows:
        return []

    # 引用检索的语义路可降级：开关关闭或远端不可用时退化为纯词法打分，
    # 而不是把整条检索链路变成 503（写入路径仍由 embed_texts 严格失败）。
    try:
        query_vec = embed_text(query)
    except EmbeddingError as exc:
        logger.warning("引用检索向量化不可用，退化为纯词法检索: %s", exc)
        query_vec = []
    query_terms = set(re.findall(r"[\u4e00-\u9fa5]{2,}|[A-Za-z0-9_.%-]+", query.lower()))
    ranked = []
    for chunk, filename, classification in rows:
        text = chunk.text or ""
        text_lower = text.lower()
        keyword_hits = sum(1 for term in query_terms if term and term in text_lower)
        cosine = (
            _cosine(query_vec, chunk.embedding or [])
            if embedding_is_compatible(chunk.meta, query_vec)
            else 0.0
        )
        score = keyword_hits * 1.5 + cosine
        if score <= 0:
            continue
        ranked.append(
            {
                "id": chunk.id, "material_id": chunk.material_id, "filename": filename,
                "chunk_index": chunk.chunk_index, "text": text, "score": round(float(score), 4),
                "meta": {**(chunk.meta or {}), "knowledgeVersion": snapshot["version"], "releaseId": snapshot["releaseId"]},
                "created_at": chunk.created_at,
                "classification": classification,
            }
        )
    ranked.sort(key=lambda item: item["score"], reverse=True)
    result = []
    seen = set()
    for hit in ranked:
        meta = hit["meta"]
        key = (hit["material_id"], meta.get("parent_chunk_index", hit["id"]))
        if key in seen:
            continue
        seen.add(key)
        result.append(hit)
        if len(result) >= limit:
            break
    for hit in result:
        data_level_var.set(max(data_level_var.get(), DataLevel[hit["classification"]]))
    return result


def _legacy_material_rows(db, material_ids):
    q = db.query(MaterialChunk, ReferenceMaterial).join(ReferenceMaterial)
    if material_ids:
        q = q.filter(MaterialChunk.material_id.in_(material_ids))
    rows = q.all()
    return [(chunk, material.filename, material.classification) for chunk, material in rows]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    denom = math.sqrt(sum(v * v for v in left)) * math.sqrt(sum(v * v for v in right))
    if not denom:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / denom
