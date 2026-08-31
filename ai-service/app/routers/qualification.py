"""资质指南文件解析接口，供 Java 管理后台通过内部令牌调用。"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile

from ..config import settings
from ..services.materials import MaterialParseError, UnsupportedFileError, parse_material
from ..services.qualification import process_task

router = APIRouter()


async def require_internal_token(request: Request) -> None:
    provided = request.headers.get("X-Internal-Token", "")
    expected = settings.ai_internal_token or ""
    if not provided or provided != expected:
        raise HTTPException(status_code=403, detail="invalid internal token")


FileUpload = Annotated[UploadFile, File(...)]


@router.post("/internal/qual/parse-guide", dependencies=[Depends(require_internal_token)])
async def parse_guide(file: FileUpload):
    data = await file.read()
    text = _parse_uploaded_text(file.filename, data)
    return {
        "text": text,
        "schema": _build_guide_schema(text),
        "materialChecklist": _build_material_checklist(text),
    }


@router.post("/internal/qual/parse-material", dependencies=[Depends(require_internal_token)])
async def parse_material_file(file: FileUpload):
    data = await file.read()
    return {"text": _parse_uploaded_text(file.filename, data)}


@router.post("/internal/qual/tasks/start", dependencies=[Depends(require_internal_token)], status_code=202)
async def start_qualification_task(payload: dict, background_tasks: BackgroundTasks):
    for field in ("taskId", "idempotencyKey"):
        if not str(payload.get(field) or "").strip():
            raise HTTPException(status_code=422, detail={"message": f"缺少任务字段：{field}"})
    background_tasks.add_task(process_task, payload)
    return {"accepted": True, "taskId": payload["taskId"]}


def _parse_uploaded_text(filename: str | None, data: bytes) -> str:
    if not data:
        raise HTTPException(status_code=422, detail={"message": "文件内容为空"})
    try:
        text = parse_material(filename or "upload.txt", data).strip()
    except (UnsupportedFileError, MaterialParseError) as exc:
        raise HTTPException(status_code=422, detail={"message": str(exc)}) from exc
    if not text:
        raise HTTPException(status_code=422, detail={"message": "文件未提取到可用文本，可能是扫描件或加密文件"})
    return text


def _build_guide_schema(text: str) -> dict:
    sections = []
    for index, title in enumerate(_section_titles(text), start=1):
        sections.append(
            {
                "key": f"section_{index}",
                "name": title,
                "title": title,
                "required": True,
                "blocks": [{"type": "text", "text": ""}],
            }
        )
    if not sections:
        sections.append(
            {
                "key": "main",
                "name": "申报要求",
                "title": "申报要求",
                "required": True,
                "blocks": [{"type": "text", "text": ""}],
            }
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "资质申报指南",
        "sections": sections,
    }


def _build_material_checklist(text: str) -> list[dict]:
    candidates = []
    for line in text.splitlines():
        clean = re.sub(r"^[\s\d（一二三四五六七八九十壹贰叁肆伍陆柒捌玖拾]+[、.)）:：-]?\s*", "", line).strip()
        if not clean or len(clean) > 80 or re.search(r"[。；;]", clean):
            continue
        if any(keyword in clean for keyword in ("证明", "证书", "报告", "申请书", "承诺书", "营业执照", "身份证明")):
            candidates.append(clean)
    seen = set()
    result = []
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        result.append({"name": name, "required": True, "optional": False})
    return result[:100]


def _section_titles(text: str) -> list[str]:
    titles = []
    for line in text.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        clean = re.sub(r"\s*(?:\d+\s*[.．…]{2,}|[.．…]{2,}\s*\d+)\s*$", "", clean).strip()
        if not clean or len(clean) > 80:
            continue
        # 带句号的整句通常是条款或清单项，不应进入章节目录。
        if clean.endswith(("。", "；", ";")):
            continue
        if re.match(
            r"^(第[一二三四五六七八九十百零0-9]+[章节部分条]"
            r"|[（(][一二三四五六七八九十百零0-9]+[）)]"
            r"|[一二三四五六七八九十]+[、.．])\s*\S"
            r"|\d+(?:\.\d+){1,3}\s+\S",
            clean,
        ):
            title = clean
            if title not in titles:
                titles.append(title)
    return titles[:80]
