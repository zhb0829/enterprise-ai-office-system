"""行业动态与竞品情报接口。Java 网关负责权限，Java 是权威数据 owner，Python 提供 AI 能力。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from ..schemas import IntelligenceSummarizeRequest
from ..security import require_internal_token
from ..services import intelligence as svc
from ..services.intelligence_client import IntelligenceJavaError, java_client

router = APIRouter()
internal_router = APIRouter()


def _guard(exc: IntelligenceJavaError) -> HTTPException:
    return HTTPException(502, f"情报数据服务暂不可用: {exc}")


def _list_sources():
    try:
        return java_client.list_sources()
    except IntelligenceJavaError as exc:
        raise _guard(exc) from exc


@router.get("/sources")
def list_sources():
    return _list_sources()


@router.get("/intelligence/items")
def intelligence_items(keyword: str = "", source: int | None = None, page: int = 1, page_size: int = 20):
    try:
        return svc.list_articles(keyword, source, page, page_size)
    except IntelligenceJavaError as exc:
        raise _guard(exc) from exc


@router.get("/intelligence/clusters")
def intelligence_clusters(topic: str = "", limit: int = 50):
    try:
        return java_client.list_clusters(topic=topic, limit=limit)
    except IntelligenceJavaError as exc:
        raise _guard(exc) from exc


@router.get("/reports/intelligence")
def intelligence_reports(period: str = "", limit: int = 20):
    try:
        return java_client.list_reports(period=period, limit=limit)
    except IntelligenceJavaError as exc:
        raise _guard(exc) from exc


@router.post("/intelligence/summarize")
def intelligence_summarize(payload: IntelligenceSummarizeRequest):
    if not payload.articleIds and not payload.clusterId:
        raise HTTPException(422, "articleIds 或 clusterId 至少提供一个")
    article_ids = list(payload.articleIds or [])
    if payload.clusterId:
        try:
            cluster = java_client.get_cluster(payload.clusterId)
        except IntelligenceJavaError as exc:
            raise _guard(exc) from exc
        if not cluster:
            raise HTTPException(404, "聚类不存在")
        article_ids = article_ids or [int(i) for i in (cluster.get("articleIds") or [])]
    try:
        return svc.summarize_articles(article_ids, payload.clusterId)
    except IntelligenceJavaError as exc:
        raise _guard(exc) from exc


@router.post("/intelligence/reports/generate")
def create_report(period: str = "daily"):
    try:
        svc.rebuild_clusters(since_days=30)
        return svc.generate_report(period)
    except IntelligenceJavaError as exc:
        raise _guard(exc) from exc


@internal_router.post(
    "/internal/intelligence/tasks/{task_id}/dispatch",
    status_code=202,
    dependencies=[Depends(require_internal_token)],
)
def internal_dispatch(task_id: int, background_tasks: BackgroundTasks):
    """Java 已创建任务行后通知 Python Worker 执行；任务与来源状态经 internal API 回写。"""
    background_tasks.add_task(svc.run_collection_task, task_id)
    return {"ok": True, "taskId": task_id, "status": "accepted"}


@internal_router.post(
    "/internal/intelligence/reports/generate",
    dependencies=[Depends(require_internal_token)],
)
def internal_generate_report(period: str = "daily"):
    try:
        svc.rebuild_clusters(since_days=30)
        return svc.generate_report(period)
    except IntelligenceJavaError as exc:
        raise HTTPException(502, f"情报数据服务暂不可用: {exc}") from exc
