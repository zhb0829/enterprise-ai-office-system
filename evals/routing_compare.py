"""G4 验收：模型分层路由前后的延迟、质量、成本三方对比（缺一不可）。

做法：起一个自建单 worker 服务（临时 SQLite + 合成语料），模型指向本地假服务——
**轻量层 30ms / 旗舰层 400ms，两个模型返回完全相同的内容与 usage**。同一组问题跑两遍，
唯一变量是运行时开关 `model_routing`（进程不重启）：

| 口径 | 期望 |
|---|---|
| 关闭（基线） | 全部走配置默认的旗舰模型，决策写明 `source=routing-disabled` |
| 开启 | 简单问题走轻量层、复杂问题走旗舰层；检索命中集合与基线完全一致 |

判定（任一不通过即非零退出码）：

1. `baseline_routing_disabled`：基线不得偷偷路由，模型必须等于配置默认值；
2. `simple_questions_use_light_tier` / `complex_questions_use_flagship`：分层真的按复杂度生效；
3. `decisions_are_auditable`：每条决策都带 tier / score / signals / reason；
4. `decisions_persisted_in_agent_run`：`agent_run.routing` 落库，可按 run 回溯；
5. `retrieval_unchanged`：两口径的检索命中条款集合一致（路由只换模型，不改检索）；
6. `quality_not_regressed`：答案非空率、引用合规率不下降，降级率不上升；
7. `latency_improved`：开启后 P50 至少改善 20%；
8. `cost_reduced`：开启后按 G6 口径的总成本下降。

**诚实边界**：假模型只证明"路由工程行为正确、链路未被破坏、延迟与账目口径正确"，
**不能**证明轻量模型在真实语料上的回答质量。真实质量必须用真实模型 + 真实语料
（`evals.run --mode live` 口径）在预生产环境复测，本报告不作为质量验收结论。
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
LIGHT_MODEL = "local-light-chat"
FLAGSHIP_MODEL = "local-flagship-chat"
PRICE_TABLE = json.dumps({
    FLAGSHIP_MODEL: {"input": 2, "output": 8},
    LIGHT_MODEL: {"input": 0.5, "output": 1},
})
ANSWER_TEXT = "依据检索到的条款，申请研发补助应提交研发费用台账与年度审计报告[引用1]。"

SIMPLE_CASES = [
    {"question": "研发补助申请需要哪些材料？", "region": "测试市"},
    {"question": "研发补助多久提交？", "region": "测试市"},
    {"question": "安全培训多久组织一次？", "industry": "制造"},
    {"question": "安全事件报告时限是多少？", "industry": "制造"},
    {"question": "个人信息是否可以向第三方提供？", "policyName": "测试数据保护规范"},
]
COMPLEX_CASES = [
    {
        "question": "企业同时申报研发补助与研发投入补助，如果两个政策对申报材料的要求存在冲突，"
                    "应当如何确定优先级，为什么？",
        "region": "测试市",
    },
    {
        "question": "对比测试市研发补助与另一市研发补助在申请材料上的差异，"
                    "并说明是否可以重复享受，为什么？",
    },
]


# ===== 本地假模型服务：按模型名区分延迟，内容与 usage 保持一致 =====

class _FakeModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    light_delay_ms = 30
    flagship_delay_ms = 400
    calls: list[str] = []

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
        _FakeModelHandler.calls.append(model)
        delay = self.light_delay_ms if model == LIGHT_MODEL else self.flagship_delay_ms
        time.sleep(delay / 1000)
        content = json.dumps({"answer": ANSWER_TEXT, "usedCitations": [1]}, ensure_ascii=False)
        return self._send({
            "id": "chatcmpl-local", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        })


class _FakeModelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):  # noqa: D102
        return


def start_fake_models(light_delay_ms: int, flagship_delay_ms: int) -> tuple[_FakeModelServer, int]:
    _FakeModelHandler.light_delay_ms = light_delay_ms
    _FakeModelHandler.flagship_delay_ms = flagship_delay_ms
    server = _FakeModelServer(("127.0.0.1", 0), _FakeModelHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


# ===== 报告与断言 =====

class Report:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.scenarios: dict = {}

    def check(self, name: str, ok: bool, detail: str, *, informative: bool = True) -> None:
        self.checks.append({
            "name": name, "passed": bool(ok), "detail": detail, "informative": bool(informative),
        })

    def scenario(self, name: str, payload: dict) -> None:
        self.scenarios[name] = payload


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _citation_valid(body: dict) -> bool:
    import re

    answer = body.get("answer") or ""
    clauses = body.get("clauses") or []
    references = {int(index) for index in re.findall(r"\[引用(\d+)\]", answer)}
    return bool(references) and all(1 <= index <= len(clauses) for index in references)


def _headers(token: str) -> dict:
    return {
        "X-Internal-Token": token, "X-User-Id": "g4-verifier", "X-Tenant-Id": "default",
        "X-User-Permissions": "policy:read,draft:write,agent:audit,agent:admin",
    }


async def set_routing(client, base: str, headers: dict, enabled: bool) -> None:
    response = await client.put(
        base + "/api/agent/flags/model_routing",
        json={"enabled": enabled, "reason": "G4 分层路由对比验收"}, headers=headers,
    )
    response.raise_for_status()


async def ask(client, base: str, headers: dict, case: dict) -> dict:
    started = time.perf_counter()
    response = await client.post(base + "/api/policy/chat", json=case, headers=headers)
    latency_ms = (time.perf_counter() - started) * 1000
    body = response.json() if response.status_code == 200 else {}
    return {
        "status": response.status_code, "latency_ms": round(latency_ms, 3),
        "model": body.get("model"), "routing": body.get("routing"),
        "clause_ids": sorted(citation.get("id") for citation in (body.get("clauses") or [])),
        "answer_length": len(body.get("answer") or ""),
        "citation_valid": _citation_valid(body),
        "degraded": body.get("degraded"), "runId": body.get("runId"),
        "question": case["question"],
    }


def load_runs(db_path: Path, run_ids: list[str]) -> dict[str, dict]:
    """从临时库里读回审计行：证明 routing 与 usage 真的落库，而不是只看响应体。"""
    placeholders = ",".join("?" for _ in run_ids)
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            f"SELECT run_id, routing, usage FROM agent_run WHERE run_id IN ({placeholders})", run_ids,
        ).fetchall()
    finally:
        connection.close()
    loaded = {}
    for run_id, routing, usage in rows:
        loaded[run_id] = {
            "routing": json.loads(routing) if isinstance(routing, str) else (routing or {}),
            "usage": json.loads(usage) if isinstance(usage, str) else (usage or {}),
        }
    return loaded


def summarize(records: list[dict], runs: dict[str, dict]) -> dict:
    latencies = [record["latency_ms"] for record in records]
    costs = [
        runs.get(record["runId"], {}).get("usage", {}).get("cost") for record in records
    ]
    known = [value for value in costs if value is not None]
    return {
        "requests": len(records),
        "models": sorted({record["model"] for record in records if record["model"]}),
        "tiers": sorted({(record["routing"] or {}).get("tier") for record in records if record["routing"]}),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "latency_mean_ms": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "answer_nonempty_rate": round(
            sum(1 for record in records if record["answer_length"] > 0) / max(1, len(records)), 4,
        ),
        "citation_valid_rate": round(
            sum(1 for record in records if record["citation_valid"]) / max(1, len(records)), 4,
        ),
        "degraded_rate": round(
            sum(1 for record in records if record["degraded"]) / max(1, len(records)), 4,
        ),
        "cost_known_sum": round(sum(known), 9) if known else None,
        "cost_calls_known": len(known),
        "currency": "CNY",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="G4 模型分层路由对比验收")
    parser.add_argument("--output", default="evals/reports/routing-compare-2026-10-26.json")
    parser.add_argument("--startup-timeout", type=int, default=300)
    parser.add_argument("--light-delay-ms", type=int, default=30)
    parser.add_argument("--flagship-delay-ms", type=int, default=400)
    parser.add_argument("--latency-improvement", type=float, default=0.2,
                        help="P50 至少改善的比例（默认 20%%）")
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    fake, fake_port = start_fake_models(args.light_delay_ms, args.flagship_delay_ms)
    report = Report()
    payload: dict = {}
    server = None

    with tempfile.TemporaryDirectory(prefix="eaos-g4-routing-", ignore_cleanup_errors=True) as directory:
        temporary = Path(directory)
        db_path = temporary / "routing.sqlite"
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
            "LLM_MODEL_TIER_REASONING": FLAGSHIP_MODEL,
            "LLM_ROUTING_ENABLED": "false",
            "LLM_ROUTING_LIGHT_MAX_SCORE": "0", "LLM_ROUTING_REASONING_MIN_SCORE": "3",
            "LLM_PRICE_TABLE": PRICE_TABLE,
            # 不配置向量与精排：本项只对比"模型选择"，引入 embedding/rerank 成本会污染口径
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

                async def verify() -> dict:
                    headers = _headers(token)
                    limits = httpx.Limits(max_connections=16, max_keepalive_connections=16)
                    async with httpx.AsyncClient(timeout=120, limits=limits, trust_env=False) as client:
                        cases = [*SIMPLE_CASES, *COMPLEX_CASES]
                        classes = ["simple"] * len(SIMPLE_CASES) + ["complex"] * len(COMPLEX_CASES)

                        await set_routing(client, base, headers, False)
                        off_records = []
                        for case, label in zip(cases, classes):
                            result = await ask(client, base, headers, case)
                            result["class"] = label
                            off_records.append(result)

                        await set_routing(client, base, headers, True)
                        on_records = []
                        for case, label in zip(cases, classes):
                            result = await ask(client, base, headers, case)
                            result["class"] = label
                            on_records.append(result)

                        run_ids = [record["runId"] for record in [*off_records, *on_records] if record["runId"]]
                        runs = load_runs(db_path, run_ids)
                        flags = (await client.get(base + "/api/agent/flags", headers=headers)).json()
                        routing_status = (
                            await client.get(base + "/api/agent/model-routing", headers=headers)
                        ).json()

                    simple_on = [record for record in on_records if record["class"] == "simple"]
                    complex_on = [record for record in on_records if record["class"] == "complex"]
                    off_summary = summarize(off_records, runs)
                    on_summary = summarize(on_records, runs)

                    report.scenario("baseline_routing_off", {
                        "summary": off_summary, "records": off_records,
                    })
                    report.scenario("routing_on", {
                        "summary": on_summary, "records": on_records,
                    })
                    report.scenario("runtime_flags", flags.get("flags"))
                    report.scenario("model_routing_status", routing_status)

                    # 1) 基线不得偷偷路由
                    off_sources = {
                        (record["routing"] or {}).get("source") for record in off_records
                    }
                    report.check(
                        "baseline_routing_disabled",
                        off_sources == {"routing-disabled"}
                        and all(record["model"] == FLAGSHIP_MODEL for record in off_records),
                        f"sources={sorted(off_sources)} models={off_summary['models']}",
                    )

                    # 2) 分层按复杂度生效
                    simple_models = sorted({record["model"] for record in simple_on})
                    complex_models = sorted({record["model"] for record in complex_on})
                    report.check(
                        "simple_questions_use_light_tier",
                        simple_models == [LIGHT_MODEL]
                        and all((record["routing"] or {}).get("tier") == "light" for record in simple_on),
                        f"simple models={simple_models} tiers="
                        f"{sorted({(record['routing'] or {}).get('tier') for record in simple_on})}",
                    )
                    report.check(
                        "complex_questions_use_flagship",
                        complex_models == [FLAGSHIP_MODEL]
                        and all((record["routing"] or {}).get("tier") == "reasoning" for record in complex_on),
                        f"complex models={complex_models} tiers="
                        f"{sorted({(record['routing'] or {}).get('tier') for record in complex_on})}",
                    )

                    # 3) 决策可审计
                    auditable = all(
                        record["routing"] and isinstance(record["routing"].get("signals"), list)
                        and record["routing"].get("reason") and record["routing"].get("tier")
                        and isinstance(record["routing"].get("score"), int)
                        for record in on_records
                    )
                    report.check(
                        "decisions_are_auditable", auditable,
                        "每条决策都带 tier/score/signals/reason",
                    )

                    # 4) 决策真的落库
                    persisted = [runs.get(record["runId"], {}) for record in on_records]
                    report.check(
                        "decisions_persisted_in_agent_run",
                        all(item.get("routing", {}).get("decisions") for item in persisted)
                        and all(item.get("routing", {}).get("enabled") is True for item in persisted),
                        f"落库 {len(persisted)} 条运行审计，"
                        f"含决策的 {sum(1 for item in persisted if item.get('routing', {}).get('decisions'))} 条",
                    )

                    # 5) 检索不受路由影响
                    off_hits = {record["question"]: record["clause_ids"] for record in off_records}
                    on_hits = {record["question"]: record["clause_ids"] for record in on_records}
                    report.check(
                        "retrieval_unchanged", off_hits == on_hits,
                        f"不一致的用例={[q for q in off_hits if off_hits[q] != on_hits.get(q)]}",
                    )
                    report.check(
                        "retrieval_has_hits",
                        all(record["clause_ids"] for record in on_records),
                        f"零命中用例={[r['question'] for r in on_records if not r['clause_ids']]}",
                    )

                    # 6) 质量不降（引用合规、答案非空、降级率）
                    quality_ok = (
                        on_summary["answer_nonempty_rate"] >= off_summary["answer_nonempty_rate"]
                        and on_summary["citation_valid_rate"] >= off_summary["citation_valid_rate"]
                        and on_summary["degraded_rate"] <= off_summary["degraded_rate"]
                    )
                    report.check(
                        "quality_not_regressed", quality_ok,
                        f"off={ {k: off_summary[k] for k in ('answer_nonempty_rate','citation_valid_rate','degraded_rate')} } "
                        f"on={ {k: on_summary[k] for k in ('answer_nonempty_rate','citation_valid_rate','degraded_rate')} }",
                        # 两个假模型内容相同 → 该判定近乎恒真，只说明"链路没被路由破坏"，
                        # 不能当作质量门禁；真实质量结论只在 live 模式有意义。
                        informative=False,
                    )

                    # 7) 延迟改善
                    threshold = (off_summary["latency_p50_ms"] or 0) * (1 - args.latency_improvement)
                    report.check(
                        "latency_improved",
                        (on_summary["latency_p50_ms"] or 0) < threshold,
                        f"P50 off={off_summary['latency_p50_ms']}ms on={on_summary['latency_p50_ms']}ms "
                        f"阈值<{round(threshold, 3)}ms",
                    )

                    # 8) 成本下降（G6 口径：已定价部分）
                    report.check(
                        "cost_reduced",
                        on_summary["cost_known_sum"] is not None
                        and off_summary["cost_known_sum"] is not None
                        and on_summary["cost_known_sum"] < off_summary["cost_known_sum"],
                        f"off={off_summary['cost_known_sum']}元 on={on_summary['cost_known_sum']}元",
                    )

                    return {
                        "flags": flags.get("flags"),
                        "model_calls": {
                            LIGHT_MODEL: _FakeModelHandler.calls.count(LIGHT_MODEL),
                            FLAGSHIP_MODEL: _FakeModelHandler.calls.count(FLAGSHIP_MODEL),
                        },
                    }

                extra = asyncio.run(verify())
                failures = [item for item in report.checks if not item["passed"]]
                payload = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "kind": "g4-model-tier-routing-compare",
                    "synthetic": True, "database": "isolated-temporary-sqlite",
                    "server_workers": 1, "platform": platform.platform(),
                    "scope": "Python AI service only; excludes Java gateway/JWT/production "
                             "PostgreSQL and real model providers",
                    "model_backend": (
                        f"local fake models: {LIGHT_MODEL} {args.light_delay_ms}ms / "
                        f"{FLAGSHIP_MODEL} {args.flagship_delay_ms}ms, identical content and usage"
                    ),
                    "settings": {
                        "lightModel": LIGHT_MODEL, "flagshipModel": FLAGSHIP_MODEL,
                        "lightMaxScore": 0, "reasoningMinScore": 3,
                        "priceTable": json.loads(PRICE_TABLE),
                    },
                    "quality_caveat": (
                        "假模型内容一致，因此本项证明的是『路由未破坏链路 + 延迟/账目口径正确』，"
                        "不构成轻量模型的真实质量结论；真实质量需 live 模式在预生产环境复测。"
                    ),
                    "phases": report.scenarios,
                    "embedded_run_summary": extra,
                    "checks": report.checks,
                    "informativeChecks": [
                        item["name"] for item in report.checks if item.get("informative") is False
                    ],
                    "informativeNote": (
                        "informativeChecks 里的判定在合成假模型下无区分度（内容相同必然相等），"
                        "只用于确认链路未被破坏；质量结论需 live 模式。"
                    ),
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
        "checks": payload.get("checks"),
        "off_p50": payload.get("phases", {}).get("baseline_routing_off", {}).get("summary", {}).get("latency_p50_ms"),
        "on_p50": payload.get("phases", {}).get("routing_on", {}).get("summary", {}).get("latency_p50_ms"),
    }, ensure_ascii=False, indent=2), flush=True)
    raise SystemExit(0 if payload.get("passed") else 1)


if __name__ == "__main__":
    main()