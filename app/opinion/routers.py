"""舆情内网接口：供 Java 业务服务调用，执行采集与 AI 分析。

调用方必须携带共享服务令牌（X-Internal-Token），否则拒绝。
所有长耗时任务立即返回任务 ID，后台异步执行。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from ..config import settings
from .collector import run_collect_job, start_run
from .java_client import java_client
from .reports import export_pdf, generate_report
from .rag import generate_suggestion, reindex_cases
from .spread import analyze as analyze_spread

logger = logging.getLogger(__name__)

internal_router = APIRouter()


async def require_internal_token(request: Request) -> None:
    provided = request.headers.get("X-Internal-Token", "")
    expected = settings.opinion_internal_token or ""
    if not provided or provided != expected:
        raise HTTPException(status_code=403, detail="invalid internal token")


@internal_router.post("/internal/opinion/sources/{source_id}/collect", status_code=202)
async def collect_source(source_id: int, payload: dict,
                         background_tasks: BackgroundTasks,
                         _: None = Depends(require_internal_token)):
    source = payload.get("source") or {}
    monitor_id = payload.get("monitorId")
    source_task_id = payload.get("sourceTaskId")
    if not source.get("id") and not source.get("homepage"):
        raise HTTPException(status_code=422, detail="缺少采集源配置")
    if not source.get("id"):
        source["id"] = source_id
    run = start_run("collect", task_id=int(source_task_id or 0),
                    monitor_id=int(monitor_id or 0), source_type=source.get("source_type", ""))
    background_tasks.add_task(run_collect_job, run.id, int(source_task_id or 0),
                              monitor_id, source)
    return {"runId": run.id, "status": "queued", "sourceId": source_id, "monitorId": monitor_id}


@internal_router.post("/internal/opinion/analysis/drain", status_code=202)
async def drain_analysis(limit: int = 50, _: None = Depends(require_internal_token)):
    from .collector import drain_analysis as _drain

    budget = min(max(limit, 0), 500)
    processed = _drain(budget)
    return {"started": True, "limit": budget, "processed": processed}


@internal_router.get("/internal/opinion/ping")
def ping(_: None = Depends(require_internal_token)):
    return {"ok": True, "service": "ai-server"}


@internal_router.get("/internal/opinion/java-health")
def java_health(_: None = Depends(require_internal_token)):
    return {"javaReachable": java_client.ping()}


# ===== 阶段五：报告能力 =====

@internal_router.post("/internal/opinion/reports/generate")
def generate_report_body(payload: dict, _: None = Depends(require_internal_token)):
    data = payload.get("data") or {}
    period = str(payload.get("period") or "daily")
    monitor_id = int(payload.get("monitorId") or 0)
    period_start = str(payload.get("periodStart") or "")
    period_end = str(payload.get("periodEnd") or "")
    return generate_report(data, period, monitor_id, period_start, period_end)


@internal_router.post("/internal/opinion/reports/pdf")
def export_report_pdf(payload: dict, _: None = Depends(require_internal_token)):
    report_id = int(payload.get("reportId") or 0)
    title = str(payload.get("title") or "")
    content_html = str(payload.get("contentHtml") or "")
    return export_pdf(report_id, title, content_html)


# ===== 阶段六：高级 AI =====

@internal_router.post("/internal/opinion/cases/reindex")
def reindex_case_index(_: None = Depends(require_internal_token)):
    try:
        return reindex_cases()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)[:500]) from exc


@internal_router.post("/internal/opinion/suggestions/generate")
def generate_suggestion_body(payload: dict, _: None = Depends(require_internal_token)):
    context = payload.get("context") or {}
    return generate_suggestion(context)


@internal_router.post("/internal/opinion/spread/analyze")
def spread_analyze(payload: dict, _: None = Depends(require_internal_token)):
    monitor_id = int(payload.get("monitorId") or 0)
    articles = payload.get("articles") or []
    return analyze_spread(monitor_id, articles)


@internal_router.post("/internal/opinion/asr/transcribe")
def asr_transcribe(payload: dict, _: None = Depends(require_internal_token)):
    """ASR 转写占位：未配置外部 ASR 服务时明确返回不支持，不伪造结果。"""
    asr_url = getattr(settings, "opinion_asr_service_url", "") or ""
    if not asr_url:
        return {"status": "unsupported", "message": "未配置外部 ASR 服务（OPINION_ASR_SERVICE_URL）"}
    return {"status": "delegated", "asrUrl": asr_url, "audioUrl": payload.get("audioUrl", "")}
