"""会议公开信息整理接口。"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from ..config import settings
from .parsers import parse_transcript
from .pipeline import run_job

internal_router = APIRouter()
ai_router = APIRouter()


async def require_internal_token(request: Request) -> None:
    provided = request.headers.get("X-Internal-Token", "")
    expected = settings.meeting_internal_token or ""
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="invalid internal token")


@internal_router.post("/internal/meeting/conferences/{conference_id}/reorganize", status_code=202)
async def reorganize(conference_id: int, payload: dict, background_tasks: BackgroundTasks,
                     _: None = Depends(require_internal_token)):
    task_id = int(payload.get("taskId") or 0)
    conference = payload.get("conference") or {}
    if task_id <= 0 or int(conference.get("id") or 0) != conference_id:
        raise HTTPException(status_code=422, detail="任务或会议参数不完整")
    if not payload.get("materials"):
        raise HTTPException(status_code=422, detail="会议至少需要一份资料")
    background_tasks.add_task(run_job, task_id, payload)
    return {"taskId": task_id, "conferenceId": conference_id, "status": "queued"}


@internal_router.get("/internal/meeting/ping")
def ping(_: None = Depends(require_internal_token)):
    return {"ok": True, "service": "meeting-worker"}


@ai_router.post("/transcript/preview")
def transcript_preview(payload: dict):
    content = str(payload.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="转录文本不能为空")
    result = parse_transcript(content)
    return {
        "hasSpeakers": result["hasSpeakers"],
        "segmentCount": len(result["segments"]),
        "speakers": list(dict.fromkeys(
            item["speaker"] for item in result["segments"] if item["speaker"]
        )),
        "segments": result["segments"][:50],
    }
