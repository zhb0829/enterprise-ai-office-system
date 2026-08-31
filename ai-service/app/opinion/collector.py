"""采集编排。

Java 触发本服务采集接口后，Python 侧异步执行：采集公开内容 → 清洗去重 →
脱敏 → 通过 Java 入库接口回传 → 调用分析接口处理已生成的分析任务。
业务数据始终存在 Java，Python 只落地自有 AI 运行记录。
"""
from __future__ import annotations

import logging
from datetime import datetime

from ..db import SessionLocal
from ..config import settings
from .adapters import collect, dedupe
from .analysis import analyze_article, sanitize_sensitive
from .java_client import java_client
from .models_ai import OpinionAiRun

logger = logging.getLogger(__name__)


def start_run(stage: str, task_id: int = 0, article_id: int = 0,
              monitor_id: int = 0, source_type: str = "") -> OpinionAiRun:
    db = SessionLocal()
    try:
        run = OpinionAiRun(stage=stage, task_id=task_id, article_id=article_id,
                           monitor_id=monitor_id, source_type=source_type, status="queued")
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    finally:
        db.close()


def update_run(run_id: int, status: str, error: str = "", model: str = "", **meta) -> None:
    db = SessionLocal()
    try:
        run = db.get(OpinionAiRun, run_id)
        if not run:
            return
        run.status = status
        run.error = (error or "")[:4000]
        if model:
            run.model = model
        if meta:
            run.meta = {**run.meta, **meta}
        if status in ("success", "failed"):
            run.finished_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("更新 AI 运行记录失败 run=%s: %s", run_id, exc)
    finally:
        db.close()


def run_collect_job(run_id: int, source_task_id: int, monitor_id: int | None, source: dict) -> None:
    try:
        update_run(run_id, "running")
        raw_items = collect(source)
        items = dedupe(raw_items)
        payload = {
            "sourceTaskId": source_task_id,
            "sourceId": source.get("id"),
            "monitorId": monitor_id,
            "items": [
                {
                    "title": sanitize_sensitive(item.get("title", "")),
                    "content": sanitize_sensitive(item.get("content", "")),
                    "url": item.get("url", ""),
                    "author": item.get("author", ""),
                    "publishTime": item.get("publish_time", ""),
                    "contentHash": item.get("content_hash", ""),
                    "urlHash": item.get("url_hash", ""),
                }
                for item in items
            ],
        }
        result = java_client.ingest_articles(payload)
        created = int(result.get("created", 0))
        duplicates = int(result.get("duplicates", 0))
        tasks = int(result.get("analysisTasks", 0))
        update_run(run_id, "success", model="collection", created=created,
                   duplicates=duplicates, analysis_tasks=tasks)
        logger.info("采集完成 source=%s monitor=%s created=%s dup=%s tasks=%s",
                    source.get("id"), monitor_id, created, duplicates, tasks)
        if tasks > 0:
            processed = drain_analysis(min(tasks, settings.opinion_analysis_budget_per_job))
            if processed:
                update_run(run_id, "success", model="collection", analyzed=processed)
    except Exception as exc:  # noqa: BLE001
        logger.exception("采集任务失败 source=%s", source.get("id"))
        try:
            if source_task_id:
                java_client.fail_source_task(source_task_id, str(exc)[:4000])
        except Exception as callback_exc:  # noqa: BLE001
            logger.warning("Java source task failure callback failed task=%s: %s",
                           source_task_id, callback_exc)
        update_run(run_id, "failed", error=str(exc)[:4000])


def drain_analysis(budget: int) -> int:
    """Worker：从 Java 领取待分析任务并提交结果，最多 budget 条。"""
    processed = 0
    for _ in range(max(0, budget)):
        task = java_client.claim_next_analysis("python-worker")
        if not task:
            break
        try:
            result = analyze_article(task)
            submit = {
                "articleId": task.get("articleId"),
                "monitorId": task.get("monitorId"),
                "sentiment": result["sentiment"],
                "confidence": result["confidence"],
                "emotionTags": result["emotionTags"],
                "reason": result["reason"],
                "evidenceIds": result["evidenceIds"],
                "riskFactors": result["riskFactors"],
                "riskScore": result["riskScore"],
                "topic": result["topic"],
                "keywords": result["keywords"],
                "model": result["model"],
                "promptVersion": result["promptVersion"],
                "aiRunId": result["aiRunId"],
            }
            java_client.submit_analysis(int(task.get("taskId")), submit)
            processed += 1
            _log_run("analyze", int(task.get("taskId")), int(task.get("articleId")),
                     int(task.get("monitorId") or 0), "success")
        except Exception as exc:  # noqa: BLE001
            logger.warning("分析任务失败 task=%s: %s", task.get("taskId"), exc)
            try:
                java_client.fail_analysis(int(task.get("taskId") or 0), str(exc)[:4000])
            except Exception as callback_exc:  # noqa: BLE001
                logger.warning("Java failure callback failed task=%s: %s",
                               task.get("taskId"), callback_exc)
            _log_run("analyze", int(task.get("taskId") or 0), int(task.get("articleId") or 0),
                     int(task.get("monitorId") or 0), "failed", str(exc)[:4000])
    return processed


def _log_run(stage: str, task_id: int, article_id: int, monitor_id: int, status: str, error: str = "") -> None:
    run = start_run(stage, task_id=task_id, article_id=article_id, monitor_id=monitor_id)
    update_run(run.id, status, error=error)
