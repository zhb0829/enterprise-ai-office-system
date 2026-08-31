"""行业政策法规智能问答 API。"""
from __future__ import annotations

import re
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import PolicyDocument
from ..schemas import (
    Citation,
    ComplianceRequest,
    ComplianceResponse,
    EmbeddingReindexResult,
    InterpretRequest,
    Interpretation,
    PolicyAnswer,
    PolicyDocumentCreate,
    PolicyDocumentOut,
    PolicyQuery,
    PolicyUrlRequest,
)
from ..services.policy import (
    answer_policy,
    check_compliance,
    create_policy_document,
    document_out,
    fetch_public_source,
    interpret_clause,
    policy_document_by_id,
    PublicSourceFetchError,
    reindex_policy_embeddings,
    search_policy_clauses,
)
from ..services.materials import EmbeddingError, parse_material

router = APIRouter()


def _safe_upload_name(filename: str | None) -> str:
    name = PureWindowsPath(PurePosixPath(filename or "policy").name).name
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return name[:180] or "policy"


@router.post("/chat", response_model=PolicyAnswer)
def policy_chat(request: PolicyQuery, db: Session = Depends(get_db)):
    try:
        return answer_policy(db, request)
    except EmbeddingError as exc:
        raise HTTPException(503, detail={"message": str(exc)}) from exc


@router.post("/interpret", response_model=Interpretation)
def policy_interpret(request: InterpretRequest, db: Session = Depends(get_db)):
    try:
        return interpret_clause(db, request)
    except ValueError as exc:
        raise HTTPException(422, detail={"message": str(exc)}) from exc


@router.post("/compliance/check", response_model=ComplianceResponse)
def compliance_check(request: ComplianceRequest, db: Session = Depends(get_db)):
    try:
        return check_compliance(db, request)
    except EmbeddingError as exc:
        raise HTTPException(503, detail={"message": str(exc)}) from exc


@router.get("/search", response_model=list[Citation])
def policy_search(
    q: str,
    industry: str = "",
    level: str = "",
    authority: str = "",
    limit: int = 6,
    db: Session = Depends(get_db),
):
    try:
        return [
            citation_for_search(hit)
            for hit in search_policy_clauses(
                db, q, industry=industry, level=level, authority=authority, limit=limit
            )
        ]
    except EmbeddingError as exc:
        raise HTTPException(503, detail={"message": str(exc)}) from exc


def citation_for_search(hit: dict) -> dict:
    clause = hit["clause"]
    document = hit["document"]
    return {
        "id": clause.id,
        "docTitle": document.title,
        "articleNo": clause.article_no,
        "excerpt": clause.content[:1200],
        "sourceUrl": document.source_url,
        "page": clause.page or 0,
        "status": document.status,
    }


@router.post("/documents", response_model=PolicyDocumentOut, status_code=201)
def create_document(request: PolicyDocumentCreate, db: Session = Depends(get_db)):
    try:
        document = create_policy_document(
            db,
            title=request.title,
            content=request.content,
            doc_number=request.docNumber,
            issuing_authority=request.issuingAuthority,
            level=request.level,
            status=request.status,
            industry_tags=request.industryTags,
            source_url=request.sourceUrl,
        )
    except EmbeddingError as exc:
        db.rollback()
        raise HTTPException(503, detail={"message": str(exc)}) from exc
    return document_out(document)


@router.post("/documents/upload", response_model=PolicyDocumentOut, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = "",
    level: str = "其他",
    industry_tags: str = "",
    source_url: str = "",
    db: Session = Depends(get_db),
):
    data = await file.read()
    if not data:
        raise HTTPException(422, detail={"message": "文件内容为空"})
    safe_name = _safe_upload_name(file.filename)
    try:
        text = parse_policy_upload(file.filename or safe_name, data)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, detail={"message": f"政策文件解析失败：{exc}"}) from exc
    try:
        document = create_policy_document(
            db,
            title=title.strip() or safe_name.rsplit(".", 1)[0],
            content=text,
            level=level,
            industry_tags=[item.strip() for item in industry_tags.split(",") if item.strip()],
            source_url=source_url,
            file_path=str(settings.upload_path / f"policy_{safe_name}"),
        )
    except EmbeddingError as exc:
        db.rollback()
        raise HTTPException(503, detail={"message": str(exc)}) from exc
    (settings.upload_path / f"policy_{document.id}_{safe_name}").write_bytes(data)
    document.file_path = str(settings.upload_path / f"policy_{document.id}_{safe_name}")
    db.commit()
    db.refresh(document)
    return document_out(document)


def parse_policy_upload(filename: str, data: bytes) -> str:
    return parse_material(filename, data)


@router.post("/documents/from-url", response_model=PolicyDocumentOut, status_code=201)
def create_document_from_url(request: PolicyUrlRequest, db: Session = Depends(get_db)):
    try:
        text = fetch_public_source(request.url)
    except PublicSourceFetchError as exc:
        raise HTTPException(exc.status_code, detail={"message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"message": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, detail={"message": f"公开链接采集失败：{exc}"}) from exc
    title = request.title.strip() or request.url.rstrip("/").rsplit("/", 1)[-1] or "公开政策文件"
    try:
        document = create_policy_document(
            db,
            title=title,
            content=text,
            level=request.level,
            industry_tags=request.industryTags,
            source_url=request.url,
        )
    except EmbeddingError as exc:
        db.rollback()
        raise HTTPException(503, detail={"message": str(exc)}) from exc
    return document_out(document)


@router.get("/documents", response_model=list[PolicyDocumentOut])
def list_documents(
    status: str = "",
    level: str = "",
    keyword: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(PolicyDocument)
    if status:
        query = query.filter(PolicyDocument.status == status)
    if level:
        query = query.filter(PolicyDocument.level == level)
    if keyword:
        query = query.filter(PolicyDocument.title.ilike(f"%{keyword}%"))
    return [document_out(item) for item in query.order_by(PolicyDocument.id.desc()).all()]


@router.get("/documents/{document_id}", response_model=PolicyDocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)):
    document = policy_document_by_id(db, document_id)
    if not document:
        raise HTTPException(404, "政策文档不存在")
    return document_out(document)


@router.post("/documents/{document_id}/status", response_model=PolicyDocumentOut)
def update_document_status(document_id: int, status: str, db: Session = Depends(get_db)):
    document = db.get(PolicyDocument, document_id)
    if not document:
        raise HTTPException(404, "政策文档不存在")
    if status not in {"现行有效", "已修订", "已废止", "有效"}:
        raise HTTPException(422, "不支持的文档时效状态")
    document.status = status
    db.commit()
    db.refresh(document)
    return document_out(document)


@router.post("/reindex", response_model=EmbeddingReindexResult)
def reindex_policy(document_id: int | None = None, db: Session = Depends(get_db)):
    try:
        return reindex_policy_embeddings(db, document_id)
    except EmbeddingError as exc:
        db.rollback()
        raise HTTPException(503, detail={"message": str(exc)}) from exc
