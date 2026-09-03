"""行业动态与竞品情报接口。Java 网关负责权限，Python 只提供业务能力。"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..models import ArticleCluster, CollectionTaskLog, IntelligenceReport, SourceConfig
from ..schemas import (
    CollectionTaskOut,
    IntelligenceReportOut,
    IntelligenceSummarizeRequest,
    SourceConfigOut,
)
from ..services.intelligence import (
    create_task,
    generate_report,
    list_articles,
    rebuild_clusters,
    run_collection_task,
    summarize_articles,
)
from ..services.celery_app import collect_source_task
from ..config import settings
from ..security import require_internal_token

router = APIRouter()
internal_router = APIRouter()


def _source_out(row: SourceConfig) -> SourceConfigOut:
    return SourceConfigOut.model_validate(row)


@router.get("/sources", response_model=list[SourceConfigOut])
def list_sources(db: Session = Depends(get_db)):
    return db.query(SourceConfig).order_by(SourceConfig.id.desc()).all()


@router.get("/intelligence/items")
def intelligence_items(keyword: str = "", source: int | None = None, page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    return list_articles(db, keyword, source, page, page_size)


@router.get("/intelligence/clusters")
def intelligence_clusters(topic: str = "", limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(ArticleCluster).order_by(ArticleCluster.report_count.desc(), ArticleCluster.updated_at.desc())
    if topic.strip():
        query = query.filter(ArticleCluster.topic.ilike(f"%{topic.strip()}%"))
    return query.limit(min(limit, 100)).all()


@router.get("/reports/intelligence", response_model=list[IntelligenceReportOut])
def intelligence_reports(period: str = "", limit: int = 20, db: Session = Depends(get_db)):
    query = db.query(IntelligenceReport)
    if period:
        query = query.filter(IntelligenceReport.period == period)
    return query.order_by(IntelligenceReport.generated_at.desc()).limit(min(limit, 100)).all()


@router.post("/intelligence/summarize")
def intelligence_summarize(payload: IntelligenceSummarizeRequest, db: Session = Depends(get_db)):
    if not payload.articleIds and not payload.clusterId:
        raise HTTPException(422, "articleIds 或 clusterId 至少提供一个")
    ids = payload.articleIds
    if payload.clusterId:
        cluster = db.get(ArticleCluster, payload.clusterId)
        if not cluster:
            raise HTTPException(404, "聚类不存在")
        ids = ids or cluster.article_ids
    return summarize_articles(db, ids, payload.clusterId)


@router.post("/intelligence/reports/generate", response_model=IntelligenceReportOut)
def create_report(period: str = "daily", db: Session = Depends(get_db)):
    rebuild_clusters(db)
    return generate_report(db, period)


@router.get("/intelligence/tasks", response_model=list[CollectionTaskOut])
def intelligence_tasks(status: str = "", source_id: int | None = None, limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(CollectionTaskLog)
    if status:
        query = query.filter(CollectionTaskLog.status == status)
    if source_id:
        query = query.filter(CollectionTaskLog.source_id == source_id)
    return query.order_by(CollectionTaskLog.created_at.desc()).limit(min(limit, 100)).all()


def trigger_collection(source_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    source = db.get(SourceConfig, source_id)
    if not source:
        raise HTTPException(404, "采集源不存在")
    if source.status == "paused":
        raise HTTPException(409, "采集源已暂停，请先恢复")
    task = create_task(db, source_id)
    if collect_source_task is not None and settings.celery_enabled:
        collect_source_task.delay(task.id)
    else:
        background_tasks.add_task(_run_background, task.id)
    return task


def retry_collection(task_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    old = db.get(CollectionTaskLog, task_id)
    if not old:
        raise HTTPException(404, "采集任务不存在")
    task = create_task(db, old.source_id, (old.retry_count or 0) + 1)
    if collect_source_task is not None and settings.celery_enabled:
        collect_source_task.delay(task.id)
    else:
        background_tasks.add_task(_run_background, task.id)
    return task


@internal_router.post(
    "/internal/intelligence/sources/{source_id}/run",
    response_model=CollectionTaskOut,
    status_code=202,
    dependencies=[Depends(require_internal_token)],
)
def internal_trigger_collection(source_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    return trigger_collection(source_id, background_tasks, db)


@internal_router.post(
    "/internal/intelligence/tasks/{task_id}/retry",
    response_model=CollectionTaskOut,
    status_code=202,
    dependencies=[Depends(require_internal_token)],
)
def internal_retry_collection(task_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    return retry_collection(task_id, background_tasks, db)


@internal_router.post(
    "/internal/intelligence/reports/generate",
    response_model=IntelligenceReportOut,
    dependencies=[Depends(require_internal_token)],
)
def internal_generate_report(period: str = "daily", db: Session = Depends(get_db)):
    rebuild_clusters(db)
    return generate_report(db, period)


def _run_background(task_id: int):
    db = SessionLocal()
    try:
        run_collection_task(db, task_id)
    finally:
        db.close()
