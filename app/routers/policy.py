"""行业政策法规智能问答 API。"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..agent.governance import audit, principal_var
from ..config import settings
from ..db import get_db
from ..models import PolicyDocument, QALog
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
    PolicyFeedback,
    PolicyFeedbackRequest,
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


@router.post("/feedback", response_model=PolicyFeedback)
def policy_feedback(request: PolicyFeedbackRequest, db: Session = Depends(get_db)):
    """线上反馈落库（点赞/点踩/是否解决），供 badcase 导出与回流测试集标注使用。

    只能反馈本租户记录；非本人记录与无属主的服务间记录均需 `agent:audit`。
    `rating=none` 表示撤销反馈。
    """
    principal = principal_var.get()
    if not principal.authenticated:
        raise HTTPException(403, detail={"message": "trusted user identity required"})
    if request.qaLogId is not None:
        row = db.query(QALog).filter(QALog.id == request.qaLogId).first()
    else:
        row = db.query(QALog).filter(QALog.run_id == request.runId).order_by(QALog.id.desc()).first()
    if not row or (row.tenant_id or "default") != principal.tenant_id:
        raise HTTPException(404, detail={"message": "问答记录不存在"})
    # user_id 为空代表服务间/后台写入的记录，没有属主：只允许审计员反馈，
    # 避免同租户任意只读用户改写问答流水、污染回流数据。
    if row.user_id:
        allowed = row.user_id == principal.user_id or "agent:audit" in principal.permissions
    else:
        allowed = "agent:audit" in principal.permissions
    if not allowed:
        raise HTTPException(403, detail={"message": "只能反馈自己的问答记录"})
    recorded_at = datetime.now(timezone.utc)
    row.feedback = "" if request.rating == "none" else request.rating
    row.resolved = request.resolved
    row.feedback_reason = request.reason
    row.feedback_user_id = principal.user_id
    row.feedback_at = recorded_at.replace(tzinfo=None)
    audit(
        db, "policy.feedback", f"qa_log:{row.id}",
        details={"rating": request.rating, "resolved": request.resolved, "reasonLength": len(request.reason)},
    )
    db.commit()
    return {
        "qaLogId": row.id, "rating": row.feedback,
        "resolved": row.resolved, "recordedAt": recorded_at,
    }


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
    region: str = "",
    policy_name: str = "",
    as_of: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return [
            citation_for_search(hit)
            for hit in search_policy_clauses(
                db, q, industry=industry, level=level, authority=authority, limit=limit,
                region=region, policy_name=policy_name, as_of=as_of,
            )
        ]
    except EmbeddingError as exc:
        raise HTTPException(503, detail={"message": str(exc)}) from exc


def citation_for_search(hit: dict) -> dict:
    from ..services.policy import citation_for
    return citation_for(hit)


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
            publish_date=request.publishDate,
            effective_date=request.effectiveDate,
            expiry_date=request.expiryDate,
            region=request.region,
            policy_version=request.policyVersion,
        )
    except EmbeddingError as exc:
        db.rollback()
        raise HTTPException(503, detail={"message": str(exc)}) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, detail={"message": str(exc)}) from exc
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
    from ..services.policy import sync_policy_document
    sync_policy_document(db, document)
    db.commit()
    db.refresh(document)
    return document_out(document)


@router.post("/reindex", response_model=EmbeddingReindexResult)
def reindex_policy(document_id: int | None = None, rechunk: bool = False, db: Session = Depends(get_db)):
    try:
        return reindex_policy_embeddings(db, document_id, rechunk=rechunk)
    except EmbeddingError as exc:
        db.rollback()
        raise HTTPException(503, detail={"message": str(exc)}) from exc
