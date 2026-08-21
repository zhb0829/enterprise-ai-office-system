"""参考素材管理接口：上传解析入库、列表、详情。"""
import re
from pathlib import PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import ReferenceMaterial
from ..schemas import MaterialChunkOut, MaterialDetail, MaterialOut
from ..services.materials import (
    MaterialParseError,
    UnsupportedFileError,
    build_material_chunks,
    parse_material,
    search_material_chunks,
)

router = APIRouter()


def _safe_upload_name(filename: str | None) -> str:
    name = PureWindowsPath(PurePosixPath(filename or "material").name).name
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    return name[:180] or "material"


@router.post("/upload", response_model=MaterialOut, status_code=201)
async def upload_material(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """上传素材文件并解析入库，返回入库记录。"""
    data = await file.read()
    if not data:
        raise HTTPException(422, detail={"message": "文件内容为空"})
    safe_name = _safe_upload_name(file.filename)
    try:
        text = parse_material(file.filename, data)
    except UnsupportedFileError as e:
        raise HTTPException(422, detail={"message": str(e)})
    except MaterialParseError as e:
        material = ReferenceMaterial(
            filename=safe_name,
            content_type=file.content_type or "",
            text_content="",
            status="解析失败",
        )
        db.add(material)
        db.flush()
        (settings.upload_path / f"{material.id}_{safe_name}").write_bytes(data)
        db.commit()
        raise HTTPException(422, detail={"message": str(e), "materialId": material.id})

    # 保存原文件到 uploads/（防重名覆盖用 id 前缀，先入库拿 id）
    material = ReferenceMaterial(
        filename=safe_name,
        content_type=file.content_type or "",
        text_content=text,
        status="已入库",
    )
    db.add(material)
    db.flush()
    chunk_count = build_material_chunks(db, material)
    material.status = f"已入库/{chunk_count}块"
    (settings.upload_path / f"{material.id}_{safe_name}").write_bytes(data)
    db.commit()
    db.refresh(material)
    return MaterialOut(
        id=material.id,
        filename=material.filename,
        content_type=material.content_type,
        status=material.status,
        text_length=len(material.text_content),
        created_at=material.created_at,
    )


@router.get("", response_model=list[MaterialOut])
def list_materials(db: Session = Depends(get_db)):
    """素材列表。"""
    rows = db.query(ReferenceMaterial).order_by(ReferenceMaterial.id.desc()).all()
    return [
        MaterialOut(
            id=r.id,
            filename=r.filename,
            content_type=r.content_type,
            status=r.status,
            text_length=len(r.text_content),
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/search", response_model=list[MaterialChunkOut])
def search_materials(
    q: str,
    material_ids: str | None = None,
    limit: int = 6,
    db: Session = Depends(get_db),
):
    """参考素材引用检索：返回最相关素材片段，用于事实依据与生成引用。"""
    ids = []
    if material_ids:
        for raw in material_ids.split(","):
            raw = raw.strip()
            if raw.isdigit():
                ids.append(int(raw))
    return search_material_chunks(db, q, ids or None, limit)


@router.get("/{material_id}", response_model=MaterialDetail)
def get_material(material_id: int, db: Session = Depends(get_db)):
    """素材详情。"""
    m = db.get(ReferenceMaterial, material_id)
    if not m:
        raise HTTPException(404, "素材不存在")
    return MaterialDetail(
        id=m.id,
        filename=m.filename,
        content_type=m.content_type,
        status=m.status,
        text_length=len(m.text_content),
        created_at=m.created_at,
        text_content=m.text_content,
    )


@router.delete("/{material_id}", status_code=204)
def delete_material(material_id: int, db: Session = Depends(get_db)):
    """删除素材记录与原始文件。"""
    m = db.get(ReferenceMaterial, material_id)
    if not m:
        raise HTTPException(404, "素材不存在")
    (settings.upload_path / f"{m.id}_{m.filename}").unlink(missing_ok=True)
    db.delete(m)
    db.commit()
    return Response(status_code=204)
