"""导出任务入口与历史查询。"""
import urllib.parse
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ExportLog
from ..schemas import ExportLogOut, ExportRequest, ExportResponse

router = APIRouter()


def _download_url(path: str) -> str:
    filename = Path(path).name
    return f"/static/exports/{urllib.parse.quote(filename)}"


def _to_out(row: ExportLog) -> ExportLogOut:
    return ExportLogOut(
        id=row.id,
        draft_id=row.draft_id,
        format=row.format,
        file_path=row.file_path,
        download_url=_download_url(row.file_path),
        created_at=row.created_at,
    )


@router.post("", response_model=ExportResponse)
def create_export(payload: ExportRequest, db: Session = Depends(get_db)):
    """创建导出任务并同步生成文件（MD/DOCX/PDF）。"""
    from ..services.export import UnsupportedExportFormat, export_draft

    try:
        path, filename = export_draft(db, payload.draftId, payload.format)
    except FileNotFoundError:
        raise HTTPException(404, "草稿不存在")
    except UnsupportedExportFormat as e:
        raise HTTPException(501, detail={"message": str(e)})

    return ExportResponse(
        file_path=path,
        download_url=f"/static/exports/{urllib.parse.quote(filename)}",
        format=payload.format,
    )


@router.get("", response_model=list[ExportLogOut])
def list_exports(
    draft_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """导出历史，可按 draft_id 过滤。"""
    q = db.query(ExportLog)
    if draft_id:
        q = q.filter(ExportLog.draft_id == draft_id)
    rows = q.order_by(ExportLog.id.desc()).limit(max(1, min(limit, 200))).all()
    return [_to_out(row) for row in rows]


@router.get("/drafts/{draft_id}", response_model=list[ExportLogOut])
def list_draft_exports(draft_id: str, db: Session = Depends(get_db)):
    """查询某个草稿的导出历史。"""
    rows = (
        db.query(ExportLog)
        .filter(ExportLog.draft_id == draft_id)
        .order_by(ExportLog.id.desc())
        .all()
    )
    return [_to_out(row) for row in rows]
