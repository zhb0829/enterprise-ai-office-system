"""Celery 可选适配。未启用 Celery 时由 FastAPI BackgroundTasks 执行同一业务函数。

情报任务与来源状态由 Java 权威保存，Celery 只承担调度与重试。
"""
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
        from .intelligence import CollectionRunError, run_collection_task
        from .intelligence_client import java_client

        try:
            run_collection_task(task_id)
        except CollectionRunError:
            task = java_client.get_task(task_id)
            if not task or task.get("status") != "failed":
                return
            source = java_client.get_source(task.get("sourceId")) if task.get("sourceId") else None
            if source and source.get("status") != "paused":
                raise CollectionRetryError(task.get("error") or f"采集任务 {task_id} 执行失败")

    @celery_app.task(name="app.services.celery_app.collect_enabled_sources")
    def collect_enabled_sources():
        from .intelligence import is_source_due
        from .intelligence_client import java_client

        for source in java_client.list_sources(status="enabled"):
            if not is_source_due(source):
                continue
            created = java_client.create_task(source["id"], 0)
            collect_source_task.delay(created["id"])

except ImportError:  # pragma: no cover - 纯离线环境
    celery_app = None
    collect_source_task = None
    collect_enabled_sources = None
