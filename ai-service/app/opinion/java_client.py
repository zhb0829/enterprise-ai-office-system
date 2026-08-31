"""Java 业务服务内部接口客户端。

Python 是纯 Worker：采集与 AI 能力在 Python，业务数据（文章/分析/事件）全经由
Java 权威接口读写。本模块封装 Java /internal/opinion/** 的调用与共享令牌。
"""
from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class JavaClientError(RuntimeError):
    """调用 Java 业务服务失败。"""


class JavaClient:
    def __init__(self) -> None:
        self.base_url = (settings.opinion_java_base_url or "").rstrip("/")
        self.token = settings.opinion_java_token
        self.headers = {
            "X-Internal-Token": self.token,
            "Content-Type": "application/json",
        }

    def ingest_articles(self, items: dict) -> dict:
        """采集结果入库：Java 负责去重、匹配监控词并生成分析任务。"""
        return self._post("/internal/opinion/articles/ingest", items)

    def claim_next_analysis(self, worker: str) -> dict | None:
        """领取下一条待分析任务；无任务返回 None。"""
        result = self._get("/internal/opinion/analysis/next", params={"worker": worker}, allow_empty=True)
        if not result:
            return None
        return result.get("task")

    def submit_analysis(self, task_id: int, result: dict) -> dict:
        """提交 AI 分析结果。"""
        return self._post(f"/internal/opinion/analysis/{task_id}/result", result)

    def fail_analysis(self, task_id: int, error: str) -> dict:
        return self._post(f"/internal/opinion/analysis/{task_id}/failure",
                          {"error": (error or "")[:4000]})

    def fail_source_task(self, task_id: int, error: str) -> dict:
        return self._post(f"/internal/opinion/source-tasks/{task_id}/failure",
                          {"error": (error or "")[:4000]})

    def ping(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/internal/opinion/ping", headers=self.headers, timeout=5)
            return response.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.warning("Java 服务不可达: %s", exc)
            return False

    def _get(self, path: str, params: dict | None = None, allow_empty: bool = False) -> dict | None:
        return self._request("GET", path, params=params, allow_empty=allow_empty)

    def _post(self, path: str, body: dict) -> dict:
        return self._request("POST", path, json=body)

    def _request(self, method: str, path: str, params=None, json=None, allow_empty: bool = False) -> dict | None:
        url = f"{self.base_url}{path}"
        headers = dict(self.headers)
        try:
            with httpx.Client(timeout=settings.llm_timeout, follow_redirects=True) as client:
                response = client.request(method, url, params=params, json=json, headers=headers)
            if response.status_code == 204:
                if allow_empty:
                    return None
                raise JavaClientError("空响应")
            if response.status_code >= 400:
                raise JavaClientError(f"Java 返回 {response.status_code}: {response.text[:300]}")
            payload = response.json()
            if isinstance(payload, dict) and payload.get("code") not in (None, 0):
                raise JavaClientError(payload.get("message", "Java 业务错误"))
            return payload
        except JavaClientError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise JavaClientError(f"请求 Java {path} 失败: {exc}") from exc


java_client = JavaClient()
