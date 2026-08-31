"""Celery 可选适配。未启用 Celery 时由 FastAPI BackgroundTasks 执行同一业务函数。"""
from ..config import settings

try:
    from celery import Celery

    celery_app = Celery("eaos_intelligence", broker=settings.redis_url, backend=settings.redis_url)
    celery_app.conf.update(
        timezone="Asia/Shanghai",
        beat_schedule={
            "intelligence-hourly": {
                "task": "app.services.celery_app.collect_enabled_sources",
                "schedule": 3600.0,
            },
        },
    )

    class CollectionRetryError(RuntimeError):
        """采集失败且来源尚未暂停时，交由 Celery 按退避策略重试。"""

    @celery_app.task(
        bind=True,
        name="app.services.celery_app.collect_source_task",
        autoretry_for=(CollectionRetryError,),
        retry_backoff=True,
        max_retries=3,
    )
    def collect_source_task(self, task_id: int):
        from ..db import SessionLocal
        from ..models import CollectionTaskLog, SourceConfig
        from .intelligence import run_collection_task

        db = SessionLocal()
        try:
            task = db.get(CollectionTaskLog, task_id)
            if task:
                task.celery_task_id = self.request.id or ""
                task.retry_count = self.request.retries
                db.commit()
            run_collection_task(db, task_id)
            task = db.get(CollectionTaskLog, task_id)
            source = db.get(SourceConfig, task.source_id) if task else None
            if task and task.status == "failed" and source and source.status != "paused":
                raise CollectionRetryError(task.error or f"采集任务 {task_id} 执行失败")
        finally:
            db.close()

    @celery_app.task(name="app.services.celery_app.collect_enabled_sources")
    def collect_enabled_sources():
        from ..db import SessionLocal
        from ..models import SourceConfig
        from .intelligence import create_task, has_active_task, is_source_due

        db = SessionLocal()
        try:
            for source in db.query(SourceConfig).filter(SourceConfig.status == "enabled").all():
                if not is_source_due(source) or has_active_task(db, source.id):
                    continue
                task = create_task(db, source.id)
                collect_source_task.delay(task.id)
        finally:
            db.close()

except ImportError:  # pragma: no cover - 纯离线环境
    celery_app = None
    collect_source_task = None
