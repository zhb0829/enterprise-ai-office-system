"""Java 权威情报数据客户端。

情报聚合表的唯一 owner 是 Java（source_config / collected_article / article_cluster /
intelligence_report / collection_task_log）。Python 只保留采集与 AI 能力，全部读写经
Java /internal/intelligence/** 完成，令牌复用 AI_INTERNAL_TOKEN（与 Java → Python 方向一致）。
"""
from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_HEADERS = {"Content-Type": "application/json"}


class IntelligenceJavaError(RuntimeError):
    """调用 Java 情报内部接口失败。"""


class IntelligenceJavaClient:
    def __init__(self) -> None:
        self.base_url = (settings.intelligence_java_base_url or "").rstrip("/")
        self.headers = {
            **_HEADERS,
            "X-Internal-Token": settings.ai_internal_token or "",
        }

    # ---------- 来源 ----------

    def list_sources(self, status: str = "") -> list[dict]:
        payload = self._get("/internal/intelligence/sources", params={"status": status})
        return payload.get("items") or []

    def get_source(self, source_id: int) -> dict | None:
        return self._get(f"/internal/intelligence/sources/{source_id}")

    def update_source_run_state(self, source_id: int, state: dict) -> dict:
        return self._post(f"/internal/intelligence/sources/{source_id}/run-state", state)

    # ---------- 文章 ----------

    def ingest_articles(self, source_id: int, items: list[dict]) -> dict:
        return self._post("/internal/intelligence/articles/batch", {"sourceId": source_id, "items": items})

    def list_articles(
        self,
        since_days: int | None = None,
        keyword: str = "",
        source_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        params = {"page": page, "pageSize": page_size}
        if since_days:
            params["sinceDays"] = since_days
        if keyword:
            params["keyword"] = keyword
        if source_id:
            params["sourceId"] = source_id
        return self._get("/internal/intelligence/articles", params=params)

    def list_articles_by_ids(self, ids: list[int]) -> list[dict]:
        if not ids:
            return []
        payload = self._get("/internal/intelligence/articles/by-ids", params={"ids": ",".join(str(i) for i in ids)})
        return payload.get("items") or []

    # ---------- 聚类 ----------

    def replace_clusters(self, clusters: list[dict]) -> dict:
        return self._post("/internal/intelligence/clusters/replace", {"clusters": clusters})

    def list_clusters(self, since_days: int | None = None, topic: str = "", limit: int = 50) -> list[dict]:
        params = {"limit": limit}
        if since_days:
            params["sinceDays"] = since_days
        if topic:
            params["topic"] = topic
        payload = self._get("/internal/intelligence/clusters", params=params)
        return payload.get("items") or []

    def get_cluster(self, cluster_id: int) -> dict | None:
        return self._get(f"/internal/intelligence/clusters/{cluster_id}")

    # ---------- 任务 ----------

    def create_task(self, source_id: int, retry_count: int = 0) -> dict:
        return self._post("/internal/intelligence/tasks", {"sourceId": source_id, "retryCount": retry_count})

    def get_task(self, task_id: int) -> dict | None:
        return self._get(f"/internal/intelligence/tasks/{task_id}")

    def mark_task_start(self, task_id: int) -> dict:
        return self._post(f"/internal/intelligence/tasks/{task_id}/start", {})

    def mark_task_result(self, task_id: int, items_count: int) -> dict:
        return self._post(f"/internal/intelligence/tasks/{task_id}/result", {"itemsCount": items_count})

    def mark_task_failure(self, task_id: int, error: str) -> dict:
        return self._post(f"/internal/intelligence/tasks/{task_id}/failure", {"error": (error or "")[:4000]})

    # ---------- 简报 ----------

    def save_report(self, payload: dict) -> dict:
        return self._post("/internal/intelligence/reports", payload)

    def list_reports(self, period: str = "", limit: int = 50) -> list[dict]:
        params = {"limit": limit}
        if period:
            params["period"] = period
        payload = self._get("/internal/intelligence/reports", params=params)
        return payload.get("items") or []

    def ping(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/internal/intelligence/ping", headers=self.headers, timeout=5)
            return response.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.warning("Java 情报服务不可达: %s", exc)
            return False

    # ---------- 底层 ----------

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        return self._request("GET", path, params=params)

    def _post(self, path: str, body: dict | None) -> dict:
        return self._request("POST", path, json=body)

    def _request(self, method: str, path: str, params=None, json=None) -> dict | None:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=settings.llm_timeout, follow_redirects=True) as client:
                response = client.request(method, url, params=params, json=json, headers=self.headers)
            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                raise IntelligenceJavaError(f"Java 情报返回 {response.status_code}: {response.text[:300]}")
            return response.json()
        except IntelligenceJavaError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise IntelligenceJavaError(f"请求 Java 情报 {path} 失败: {exc}") from exc


java_client = IntelligenceJavaClient()
