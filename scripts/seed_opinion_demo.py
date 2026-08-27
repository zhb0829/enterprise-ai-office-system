"""灌入一套可直接验收舆情功能的本地演示数据。

前置条件：
1. PostgreSQL 已启动；
2. Java admin-server 在 8080；
3. Python ai-server 在 8000；
4. Java 管理员账号仍为开发默认值 admin/admin123，或通过参数传入。

脚本只调用现有 HTTP 接口，不直接写业务表。重复执行会创建新的演示监控，
便于验证幂等、版本和历史数据展示。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.opinion.demo_data import DEMO_MONITOR, DEMO_RESPONSE_CASES, build_demo_articles, build_demo_source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="创建并分析一套舆情演示数据")
    parser.add_argument("--java-url", default="http://localhost:8080")
    parser.add_argument("--ai-url", default="http://localhost:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--internal-token", default="eaos-opinion-internal-dev-token")
    parser.add_argument("--run-tag", default="")
    parser.add_argument("--cases-only", action="store_true", help="仅初始化相似应对参考案例并重建 RAG 索引")
    return parser.parse_args()


class DemoClient:
    def __init__(self, java_url: str, ai_url: str, internal_token: str):
        self.java_url = java_url.rstrip("/")
        self.ai_url = ai_url.rstrip("/")
        self.internal_token = internal_token
        self.token = ""
        self.client = httpx.Client(timeout=60, follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def login(self, username: str, password: str) -> None:
        payload = self._request(
            "POST",
            f"{self.java_url}/api/auth/login",
            json={"username": username, "password": password},
            unwrap=True,
        )
        self.token = str(payload["token"])

    def java(self, method: str, path: str, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return self._request(method, f"{self.java_url}{path}", headers=headers, unwrap=True, **kwargs)

    def java_internal(self, method: str, path: str, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["X-Internal-Token"] = self.internal_token
        return self._request(method, f"{self.java_url}{path}", headers=headers, unwrap=False, **kwargs)

    def ai_internal(self, method: str, path: str, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["X-Internal-Token"] = self.internal_token
        return self._request(method, f"{self.ai_url}{path}", headers=headers, unwrap=False, **kwargs)

    def _request(self, method: str, url: str, unwrap: bool, **kwargs):
        response = self.client.request(method, url, **kwargs)
        try:
            body = response.json()
        except ValueError:
            body = response.text
        if response.status_code >= 400:
            raise RuntimeError(f"{method} {url} -> {response.status_code}: {body}")
        if response.status_code == 204:
            return None
        if unwrap and isinstance(body, dict) and "code" in body:
            if body["code"] != 0:
                raise RuntimeError(f"{method} {url} -> {body.get('message', body)}")
            return body.get("data")
        return body


def run(args: argparse.Namespace) -> dict:
    tag = args.run_tag or datetime.now().strftime("%Y%m%d%H%M%S")
    client = DemoClient(args.java_url, args.ai_url, args.internal_token)
    try:
        client.login(args.username, args.password)
        case_result = ensure_demo_cases(client)
        if args.cases_only:
            return {"caseResult": case_result}

        monitor_payload = {**DEMO_MONITOR, "name": f"{DEMO_MONITOR['name']}-{tag}"}
        monitor = client.java("POST", "/api/opinion/monitors", json=monitor_payload)
        monitor_id = monitor["id"]

        source = client.java(
            "POST",
            "/api/opinion/sources",
            json=build_demo_source(tag),
        )
        source_id = source["id"]
        client.java(
            "POST",
            f"/api/opinion/sources/{source_id}/audit",
            json={"auditStatus": "approved", "auditNote": "本地演示数据源，数据由测试脚本灌入"},
        )

        rule = client.java(
            "POST",
            "/api/opinion/alert-rules",
            json={
                "monitorId": monitor_id,
                "name": f"负面文章数量预警-{tag}",
                "riskLevel": "预警",
                "trigger": {"negativeCount": 2, "windowHours": 24},
                "cooldownMinutes": 1,
                "escalate": {"warningCount": 2, "crisisCount": 3},
                "status": "enabled",
            },
        )

        ingest = client.java_internal(
            "POST",
            "/internal/opinion/articles/ingest",
            json={
                "sourceId": source_id,
                "monitorId": monitor_id,
                "items": build_demo_articles(tag),
            },
        )
        drained = client.ai_internal(
            "POST",
            "/internal/opinion/analysis/drain?limit=20",
        )
        spread = client.java(
            "POST",
            f"/api/opinion/spread/analyze?monitorId={monitor_id}",
        )
        events = client.java(
            "GET",
            f"/api/opinion/events?monitorId={monitor_id}",
        )
        alerts = client.java(
            "GET",
            f"/api/opinion/alerts?monitorId={monitor_id}",
        )
        report = client.java(
            "POST",
            f"/api/opinion/reports/generate?monitorId={monitor_id}&period=daily",
        )

        if not ingest.get("created"):
            raise RuntimeError(f"演示文章未入库: {ingest}")
        if drained.get("processed", 0) < 4:
            raise RuntimeError(f"分析任务未全部处理: {drained}")
        if not events:
            raise RuntimeError("未生成热点事件")
        if not alerts:
            raise RuntimeError("未触发告警，请检查告警规则或时间窗口")

        return {
            "tag": tag,
            "monitorId": monitor_id,
            "sourceId": source_id,
            "alertRuleId": rule["id"],
            "ingest": ingest,
            "analysis": drained,
            "spread": spread,
            "eventCount": len(events),
            "alertCount": len(alerts),
            "reportId": report["id"],
            "caseResult": case_result,
        }
    finally:
        client.close()


def ensure_demo_cases(client: DemoClient) -> dict:
    existing = client.java("GET", "/api/opinion/cases")
    titles = {str(item.get("title") or "") for item in existing}
    created = 0
    for case in DEMO_RESPONSE_CASES:
        if case["title"] in titles:
            continue
        client.java("POST", "/api/opinion/cases", json=case)
        created += 1
    index = client.java("POST", "/api/opinion/cases/reindex")
    return {"created": created, "total": len(DEMO_RESPONSE_CASES), "index": index}


def main() -> int:
    args = parse_args()
    try:
        result = run(args)
    except Exception as exc:  # noqa: BLE001
        print(f"[舆情演示失败] {exc}", file=sys.stderr)
        return 1

    print("[舆情演示成功]")
    case_result = result["caseResult"]
    print(f"相似应对参考案例: 新增 {case_result['created']} / {case_result['total']}，索引切片 {case_result['index'].get('chunks', 0)} 个")
    if args.cases_only:
        return 0
    print(f"监控任务: {result['monitorId']}")
    print(f"采集来源: {result['sourceId']}")
    print(f"告警规则: {result['alertRuleId']}")
    print(f"入库结果: {result['ingest']}")
    print(f"分析结果: {result['analysis']}")
    print(f"热点事件: {result['eventCount']} 个")
    print(f"告警事件: {result['alertCount']} 个")
    print(f"日报编号: {result['reportId']}")
    print("用户端打开: http://localhost:5173/workspace/opinion")
    print("舆情告警: http://localhost:5173/workspace/opinion-alerts")
    print("舆情报告: http://localhost:5173/workspace/opinion-reports")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
