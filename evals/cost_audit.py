"""G6 验收：成本是否真的"按租户 / 按功能 / 按模型"可核算，且未知成本不被伪造。

做法：起一个自建单 worker 服务（临时 SQLite + 合成语料），模型指向本地假服务，
**价格表只收录旗舰模型、故意不收录轻量模型**，然后造两个租户、两种功能的流量：

| 流量 | 期望账目 |
|---|---|
| 复杂政策问答（旗舰模型，已定价） | token 与金额可精确复算（10 in / 8 out × 单价） |
| 简单政策问答 + 条款解读（轻量模型，未定价） | 记 token、记调用次数，**成本为 null** |

判定（任一不通过即非零退出码）：

1. `cost_query_requires_audit`：成本查询需 `agent:audit`，跨租户/全平台需 `agent:admin`；
2. `cost_grouped_by_tenant` / `cost_grouped_by_intent` / `cost_grouped_by_purpose` /
   `cost_grouped_by_model`：租户、业务功能（intent）、模型用途（purpose）、模型四个维度都能分组；
3. `intent_filter_narrows_scope`：按业务功能过滤时窗口真的收窄；
4. `tokens_match_provider_usage`：明细里的 token 与供应商返回的 usage 一致；
5. `priced_cost_matches_tokens`：已定价模型的金额 = Σ(tokens × 单价)，可复算；
6. `unpriced_model_is_null_not_zero`：未定价模型的 `cost` 为 null，**不按 0 顶替**；
7. `partial_total_exposes_gap`：总额只含已知部分，并用 `costComplete=false` + `unpricedModels` 自曝缺口；
8. `usage_persisted_with_model_and_purpose`：明细真的落进 `agent_run.usage`（不是只在内存里算）。

**诚实边界**：价格表是配置口径，不是供应商账单；本项证明的是"账目算法与数据链路正确"，
真实账单核对需要真实模型的结算数据。空价格表（完全未知）由 `tests/test_g6_cost.py` 覆盖。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx

ROOT = Path(__file__).resolve().parents[1]
FLAGSHIP_MODEL = "local-flagship-chat"
LIGHT_MODEL = "local-light-chat"
INPUT_TOKENS, OUTPUT_TOKENS = 10, 8
FLAGSHIP_INPUT_PRICE, FLAGSHIP_OUTPUT_PRICE = 2.0, 8.0
FLAGSHIP_CALL_COST = round(
    INPUT_TOKENS / 1_000_000 * FLAGSHIP_INPUT_PRICE + OUTPUT_TOKENS / 1_000_000 * FLAGSHIP_OUTPUT_PRICE, 9,
)
# 只收录旗舰模型：轻量模型必须记 null，不允许用 0 顶替
PRICE_TABLE = json.dumps({FLAGSHIP_MODEL: {"input": FLAGSHIP_INPUT_PRICE, "output": FLAGSHIP_OUTPUT_PRICE}})

TENANTS = ("tenant-a", "tenant-b")
SIMPLE_QUESTION = "研发补助申请需要哪些材料？"
COMPLEX_QUESTION = (
    "企业同时申报研发补助与研发投入补助，如果两个政策对申报材料的要求存在冲突，"
    "应当如何确定优先级，为什么？"
)
DOCUMENT = {
    "title": "测试研发补助办法",
    "content": (
        "第一条 申请研发补助的企业应当提交研发费用台账与年度审计报告。\n"
        "第二条 同一项目不得重复享受市级与区级补助，存在冲突时按就高不重复原则执行。\n"
        "第三条 申报截止时间为每年6月30日。"
    ),
    "region": "测试市",
    "industryTags": ["科技"],
}

ANSWER_JSON = json.dumps({
    "answer": "按测试研发补助办法，申请需提交研发费用台账与年度审计报告[引用1]。",
    "usedCitations": [1],
    "plainSummary": "该条要求企业提交研发费用台账与年度审计报告。",
    "applicableObjects": ["科技企业"],
    "obligations": ["提交研发费用台账"],
    "prohibitions": [],
    "consequences": [],
}, ensure_ascii=False)


# ===== 本地假模型服务 =====

class _FakeModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    delay_ms = 20

    def log_message(self, *args):  # noqa: D102
        return

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, OSError):
            return

    def do_POST(self):  # noqa: N802  http.server 约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}
        if not self.path.endswith("/chat/completions"):
            return self._send({"detail": "not found"}, status=404)
        model = str(payload.get("model") or FLAGSHIP_MODEL)
        time.sleep(self.delay_ms / 1000)
        return self._send({
            "id": "chatcmpl-local", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": ANSWER_JSON},
                         "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": INPUT_TOKENS, "completion_tokens": OUTPUT_TOKENS,
                "total_tokens": INPUT_TOKENS + OUTPUT_TOKENS,
            },
        })


class _FakeModelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):  # noqa: D102
        return


def start_fake_models(delay_ms: int) -> tuple[_FakeModelServer, int]:
    _FakeModelHandler.delay_ms = delay_ms
    server = _FakeModelServer(("127.0.0.1", 0), _FakeModelHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


# ===== 断言工具 =====

class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.scenarios: dict = {}

    def check(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append({"name": name, "passed": bool(ok), "detail": detail})

    def scenario(self, name: str, payload: dict) -> None:
        self.scenarios[name] = payload


def _headers(token: str, tenant: str, permissions: str) -> dict:
    return {
        "X-Internal-Token": token, "X-User-Id": "g6-auditor", "X-Tenant-Id": tenant,
        "X-User-Permissions": permissions,
    }


def _group(report: dict, **dims) -> dict | None:
    for group in report.get("groups") or []:
        if all(group.get(key) == value for key, value in dims.items()):
            return group
    return None


def load_run_usage(db_path: Path) -> list[dict]:
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT run_id, tenant_id, intent, usage FROM agent_run ORDER BY started_at",
        ).fetchall()
    finally:
        connection.close()
    loaded = []
    for run_id, tenant, intent, usage in rows:
        loaded.append({
            "runId": run_id, "tenantId": tenant, "intent": intent,
            "usage": json.loads(usage) if isinstance(usage, str) else (usage or {}),
        })
    return loaded


async def run(base: str, token: str, db_path: Path, report: Report) -> dict:
    admin = _headers(token, "tenant-a", "policy:read,agent:audit,agent:admin,knowledge:publish")
    limits = httpx.Limits(max_connections=16, max_keepalive_connections=16)
    traffic = []
    async with httpx.AsyncClient(timeout=120, limits=limits, trust_env=False) as client:
        # 每个租户都建自己的语料：成本必须能按租户归集，而不是只有一个 default
        for tenant in TENANTS:
            headers = _headers(token, tenant, "policy:read,knowledge:publish")
            created = await client.post(base + "/api/policy/documents", json=DOCUMENT, headers=headers)
            if created.status_code != 201:
                raise RuntimeError(f"为 {tenant} 建语料失败：HTTP {created.status_code} {created.text[:200]}")

        for tenant in TENANTS:
            headers = _headers(token, tenant, "policy:read,agent:audit")
            simple = await client.post(
                base + "/api/policy/chat", json={"question": SIMPLE_QUESTION}, headers=headers,
            )
            complex_answer = await client.post(
                base + "/api/policy/chat", json={"question": COMPLEX_QUESTION}, headers=headers,
            )
            interpretation = await client.post(
                base + "/api/policy/interpret",
                json={"clauseText": "企业申请研发补助应当提交研发费用归集表。"}, headers=headers,
            )
            traffic.append({
                "tenant": tenant,
                "simple": {
                    "status": simple.status_code,
                    "model": (simple.json().get("model") if simple.status_code == 200 else None),
                    "tier": ((simple.json().get("routing") or {}).get("tier") if simple.status_code == 200 else None),
                },
                "complex": {
                    "status": complex_answer.status_code,
                    "model": (complex_answer.json().get("model") if complex_answer.status_code == 200 else None),
                    "tier": ((complex_answer.json().get("routing") or {}).get("tier")
                             if complex_answer.status_code == 200 else None),
                },
                "interpret": {
                    "status": interpretation.status_code,
                    "model": (interpretation.json().get("model") if interpretation.status_code == 200 else None),
                    "tier": ((interpretation.json().get("routing") or {}).get("tier")
                             if interpretation.status_code == 200 else None),
                },
            })

        # 权限边界：只看成本也需要 agent:audit；全平台口径需要 agent:admin
        denied = await client.get(base + "/api/agent/costs", headers=_headers(token, "tenant-a", "policy:read"))
        all_tenants = await client.get(
            base + "/api/agent/costs?tenant=all-tenants&groupBy=model,purpose,tenant", headers=admin,
        )
        by_model = await client.get(
            base + "/api/agent/costs?tenant=all-tenants&groupBy=model", headers=admin,
        )
        by_intent = await client.get(
            base + "/api/agent/costs?tenant=all-tenants&groupBy=intent", headers=admin,
        )
        by_purpose = await client.get(
            base + "/api/agent/costs?tenant=all-tenants&groupBy=purpose", headers=admin,
        )
        by_tenant = await client.get(
            base + "/api/agent/costs?tenant=all-tenants&groupBy=tenant", headers=admin,
        )
        filtered = await client.get(
            base + "/api/agent/costs?tenant=all-tenants&intent=policy_interpretation&groupBy=model",
            headers=admin,
        )

    body = all_tenants.json()
    model_report = by_model.json()
    intent_report = by_intent.json()
    purpose_report = by_purpose.json()
    tenant_report = by_tenant.json()
    filtered_report = filtered.json()
    runs = load_run_usage(db_path)

    report.scenario("traffic", traffic)
    report.scenario("cost_report", body)
    report.scenario("by_model", model_report)
    report.scenario("by_intent", intent_report)
    report.scenario("by_purpose", purpose_report)
    report.scenario("by_tenant", tenant_report)
    report.scenario("intent_filtered", filtered_report)
    report.scenario("agent_run_usage", [
        {"runId": item["runId"], "tenantId": item["tenantId"], "intent": item["intent"],
         "models": sorted((item["usage"].get("by_model") or {}).keys()),
         "cost": item["usage"].get("cost"), "costComplete": item["usage"].get("cost_complete")}
        for item in runs
    ])
    report.scenario("permission_probe", {
        "audit_denied_status": denied.status_code,
        "all_tenants_status": all_tenants.status_code,
    })

    # 1) 权限边界
    report.check(
        "cost_query_requires_audit",
        denied.status_code == 403 and all_tenants.status_code == 200,
        f"policy:read={denied.status_code} agent:admin={all_tenants.status_code}",
    )

    # 2) 三个维度都能分组
    tenants = {group["tenant"] for group in tenant_report["groups"]}
    intents = {group["intent"] for group in intent_report["groups"]}
    purposes = {group["purpose"] for group in purpose_report["groups"]}
    models = {group["model"] for group in model_report["groups"]}
    report.check("cost_grouped_by_tenant", tenants == set(TENANTS), f"tenants={sorted(tenants)}")
    report.check(
        "cost_grouped_by_intent",
        intents == {"policy_qa", "policy_interpretation"},
        f"intents={sorted(intents)}",
    )
    report.check(
        "cost_grouped_by_purpose",
        purposes == {"policy.answer", "policy.interpret"},
        f"purposes={sorted(purposes)}",
    )
    report.check(
        "cost_grouped_by_model", models == {FLAGSHIP_MODEL, LIGHT_MODEL}, f"models={sorted(models)}",
    )
    report.check(
        "intent_filter_narrows_scope",
        filtered_report["window"]["intent"] == "policy_interpretation"
        and filtered_report["total"]["runs"] == len(TENANTS)
        and {group["model"] for group in filtered_report["groups"]} == {LIGHT_MODEL},
        f"runs={filtered_report['total']['runs']} models="
        f"{sorted({group['model'] for group in filtered_report['groups']})}",
    )

    # 3) token 明细与供应商 usage 一致
    flagship = _group(model_report, model=FLAGSHIP_MODEL) or {}
    light = _group(model_report, model=LIGHT_MODEL) or {}
    calls = int(flagship.get("calls") or 0)
    report.check(
        "tokens_match_provider_usage",
        calls >= len(TENANTS)
        and flagship.get("inputTokens") == calls * INPUT_TOKENS
        and flagship.get("outputTokens") == calls * OUTPUT_TOKENS,
        f"calls={calls} input={flagship.get('inputTokens')} output={flagship.get('outputTokens')}",
    )

    # 4) 已定价金额可复算
    expected_cost = round(calls * FLAGSHIP_CALL_COST, 9)
    report.check(
        "priced_cost_matches_tokens",
        flagship.get("cost") is not None and abs(flagship["cost"] - expected_cost) < 1e-12,
        f"实际={flagship.get('cost')} 期望={expected_cost}（{calls} 次 × {FLAGSHIP_CALL_COST} 元）",
    )

    # 5) 未定价模型：记 token、记调用次数，成本必须是 null
    report.check(
        "unpriced_model_is_null_not_zero",
        int(light.get("calls") or 0) >= len(TENANTS)
        and light.get("cost") is None
        and light.get("costComplete") is False
        and light.get("inputTokens") == int(light.get("calls") or 0) * INPUT_TOKENS,
        f"calls={light.get('calls')} cost={light.get('cost')} complete={light.get('costComplete')}",
    )

    # 6) 总额只含已知部分，并自曝缺口
    total = body.get("total") or {}
    report.check(
        "partial_total_exposes_gap",
        body.get("costComplete") is False
        and body.get("unpricedModels") == [LIGHT_MODEL]
        and total.get("cost") is not None
        and abs(total["cost"] - expected_cost) < 1e-12,
        f"total={total.get('cost')} costComplete={body.get('costComplete')} "
        f"unpriced={body.get('unpricedModels')}",
    )

    # 7) 明细真的落库（可按 run 回溯到模型与用途）
    with_detail = [
        item for item in runs
        if item["usage"].get("by_model")
        and any(bucket.get("purposes") for bucket in item["usage"]["by_model"].values())
    ]
    report.check(
        "usage_persisted_with_model_and_purpose",
        len(with_detail) == len([item for item in runs if item["usage"].get("by_model")])
        and len(runs) >= len(TENANTS) * 2,
        f"落库运行 {len(runs)} 条，含模型×用途明细 {len(with_detail)} 条",
    )

    return {
        "flagshipCalls": calls,
        "lightCalls": int(light.get("calls") or 0),
        "expectedFlagshipCost": expected_cost,
        "reportedTotalCost": total.get("cost"),
        "runsPersisted": len(runs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="G6 成本核算口径验收")
    parser.add_argument("--output", default="evals/reports/cost-audit-2026-10-26.json")
    parser.add_argument("--startup-timeout", type=int, default=300)
    parser.add_argument("--model-delay-ms", type=int, default=20)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fake, fake_port = start_fake_models(args.model_delay_ms)
    report = Report()
    payload: dict = {}
    server = None

    with tempfile.TemporaryDirectory(prefix="eaos-g6-cost-", ignore_cleanup_errors=True) as directory:
        temporary = Path(directory)
        db_path = temporary / "cost.sqlite"
        token = secrets.token_hex(24)
        env = os.environ.copy()
        env.update({
            "DATABASE_URL": "sqlite:///" + db_path.as_posix(),
            "APP_ENV": "test", "AI_INTERNAL_TOKEN": token,
            "EXPORT_DIR": str(temporary / "exports"), "UPLOAD_DIR": str(temporary / "uploads"),
            "PYTHONUTF8": "1", "CELERY_ENABLED": "false",
            "LLM_API_KEY": "local-fake", "LLM_BASE_URL": f"http://127.0.0.1:{fake_port}/v1",
            "LLM_MODEL_GENERATION": FLAGSHIP_MODEL, "LLM_MODEL_EXTRACTION": FLAGSHIP_MODEL,
            "LLM_MODEL_FACTCHECK": FLAGSHIP_MODEL, "LLM_TIMEOUT": "30",
            "LLM_MODEL_TIER_LIGHT": LIGHT_MODEL, "LLM_MODEL_TIER_STANDARD": FLAGSHIP_MODEL,
            "LLM_MODEL_TIER_REASONING": FLAGSHIP_MODEL, "LLM_ROUTING_ENABLED": "true",
            "LLM_PRICE_TABLE": PRICE_TABLE,
            "EMBEDDING_API_KEY": "", "RERANK_URL": "", "RERANK_LOCAL_MODEL": "",
            "KG_ENABLED": "false", "RATE_LIMIT_ENABLED": "false",
        })
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        with output.with_suffix(".log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "evals.benchmark_app:app",
                 "--host", "127.0.0.1", "--port", str(port), "--no-access-log"],
                cwd=ROOT, env=env, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                deadline = time.monotonic() + args.startup_timeout
                with httpx.Client(timeout=3, trust_env=False) as probe_client:
                    ready = False
                    while time.monotonic() < deadline:
                        if server.poll() is not None:
                            break
                        try:
                            ready = probe_client.get(base + "/api/health").status_code == 200
                        except httpx.HTTPError:
                            pass
                        if ready:
                            break
                        time.sleep(0.25)
                if not ready:
                    raise RuntimeError(f"服务启动失败，见 {output.with_suffix('.log')}")

                summary = asyncio.run(run(base, token, db_path, report))
                failures = [item for item in report.checks if not item["passed"]]
                payload = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "kind": "g6-cost-accounting-audit",
                    "synthetic": True, "database": "isolated-temporary-sqlite",
                    "server_workers": 1, "platform": platform.platform(),
                    "scope": "Python AI service only; excludes Java gateway/JWT/production PostgreSQL",
                    "model_backend": f"local fake model {FLAGSHIP_MODEL} (usage {INPUT_TOKENS}in/{OUTPUT_TOKENS}out)",
                    "pricing": {
                        "currency": "CNY", "unit": "per_million_tokens",
                        "table": json.loads(PRICE_TABLE),
                        "intentionallyUnpriced": LIGHT_MODEL,
                        "flagshipCostPerCall": FLAGSHIP_CALL_COST,
                    },
                    "pricing_caveat": (
                        "价格表是配置口径而非供应商账单；本项只证明账目算法与数据链路正确，"
                        "真实账单核对需要供应商结算数据；空价格表（完全未知）由单元测试覆盖。"
                    ),
                    "summary": summary,
                    "scenarios": report.scenarios,
                    "checks": report.checks,
                    "failures": [item["name"] for item in failures],
                    "passed": not failures and bool(report.checks),
                    "completed": True,
                    "production_accepted": False,
                }
                output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            finally:
                if os.name == "nt" and server is not None:
                    subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True)
                elif server is not None:
                    server.terminate()
                if server is not None:
                    try:
                        server.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=15)
    fake.shutdown()
    fake.server_close()
    print(json.dumps({
        "passed": payload.get("passed"), "failures": payload.get("failures"),
        "summary": payload.get("summary"), "checks": payload.get("checks"),
    }, ensure_ascii=False, indent=2), flush=True)
    raise SystemExit(0 if payload.get("passed") else 1)


if __name__ == "__main__":
    main()