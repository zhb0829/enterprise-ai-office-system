"""会议 Worker 回调 Java 权威业务服务。"""
from __future__ import annotations

import httpx

from ..config import settings


class MeetingJavaClient:
    def __init__(self) -> None:
        self.base_url = settings.meeting_java_base_url.rstrip("/")
        self.headers = {
            "X-Internal-Token": settings.meeting_java_token,
            "Content-Type": "application/json",
        }

    def progress(self, task_id: int, steps: list[dict], materials: list[dict], status: str = "running") -> None:
        self._post(f"/internal/meeting/tasks/{task_id}/progress", {
            "status": status,
            "steps": steps,
            "materials": _material_updates(materials),
        })

    def result(self, task_id: int, payload: dict) -> None:
        self._post(f"/internal/meeting/tasks/{task_id}/result", payload)

    def failure(self, task_id: int, error: str) -> None:
        self._post(f"/internal/meeting/tasks/{task_id}/failure", {"error": (error or "")[:4000]})

    def _post(self, path: str, body: dict) -> dict:
        with httpx.Client(timeout=max(settings.llm_timeout, 180), follow_redirects=True) as client:
            response = client.post(f"{self.base_url}{path}", headers=self.headers, json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"Java 回调失败 {response.status_code}: {response.text[:300]}")
        data = response.json() if response.content else {}
        if isinstance(data, dict) and data.get("code") not in (None, 0):
            raise RuntimeError(str(data.get("message") or "Java 业务回调失败"))
        return data


def _material_updates(materials: list[dict]) -> list[dict]:
    return [{
        "id": item.get("id"),
        "parseStatus": item.get("parseStatus", "pending"),
        "parseResult": item.get("parseResult") or {},
    } for item in materials]


java_client = MeetingJavaClient()
