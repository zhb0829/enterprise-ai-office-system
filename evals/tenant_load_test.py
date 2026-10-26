"""G3 多租户资源隔离压测：单租户打满不得挤占其他租户，超限必须快速失败。

两个受控阶段，跑在同一个自建、临时 SQLite 的单 worker 服务上：

1. `rate_limit_isolation`：`noisy` 租户配额被压到 rps=2 / burst=4，并发打 12 个请求，
   必须出现 429（带 `Retry-After`）；同时 `quiet` 租户并发请求必须零错误、零 429、P95 达标。
2. `capacity_fast_fail`：本地假向量/精排服务被调成 600ms 慢响应，
   Embedding 池 2 并发 + 2 排队、Rerank 池 1 并发 + 1 排队；两个租户各 20 并发同时打，
   必须**全部 200**（降级而不是 500/无界排队），且出现容量快速失败计数与降级标记，
   请求耗时上界远低于"无限排队"的理论值。

边界（必须如实保留）：只覆盖 Python AI 服务直连，不含 Java 网关、JWT、生产 PostgreSQL、
外部网络与真实模型配额；`passed` 不等于预生产完整链路验收。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx

ROOT = Path(__file__).resolve().parents[1]
POLICY_QUESTION = "研发补助申请需要什么材料？"


# ===== 本地假模型服务：可动态调慢，用于制造容量池饱和 =====

class _FakeModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    delay = 0.02

    def log_message(self, *args):  # noqa: D102  压测输出保持干净
        return

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionError, OSError):
            # 压测中断连属正常现象，不得污染报告与退出码
            return

    def do_POST(self):  # noqa: N802  http.server 约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}
        if self.path.endswith("/control/delay"):
            _FakeModelHandler.delay = max(0.0, float(payload.get("seconds") or 0))
            return self._send({"delay": _FakeModelHandler.delay})
        time.sleep(_FakeModelHandler.delay)
        if self.path.endswith("/embeddings"):
            inputs = payload.get("input") or []
            if isinstance(inputs, str):
                inputs = [inputs]
            dimensions = int(payload.get("dimensions") or 64)
            data = [
                {"object": "embedding", "index": index,
                 "embedding": [round(0.01 * (index + 1), 6)] * dimensions}
                for index in range(len(inputs))
            ]
            return self._send({"object": "list", "data": data, "model": payload.get("model", "local-fake")})
        if self.path.endswith("/rerank"):
            documents = payload.get("documents") or []
            return self._send({"results": [
                {"index": index, "relevance_score": round(1.0 - index * 0.01, 4)}
                for index in range(len(documents))
            ]})
        return self._send({"detail": "not found"}, status=404)


class _FakeModelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):  # noqa: D102  断连不打印噪音
        return


def start_fake_models() -> tuple[_FakeModelServer, int]:
    server = _FakeModelServer(("127.0.0.1", 0), _FakeModelHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


# ===== 压测执行 =====

def percentile(values, p):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * p) - 1)], 2)


async def fire(client, base, *, tenant, concurrency, requests):
    """对单个租户发起一轮并发请求，返回状态码/延迟/降级统计。"""
    semaphore = asyncio.Semaphore(concurrency)
    barrier = asyncio.Event()
    latencies: list[float] = []
    statuses: Counter = Counter()
    errors: list[dict] = []
    degraded = 0
    dense_degraded = 0
    retry_after: list[str] = []

    async def one(index: int) -> None:
        nonlocal degraded, dense_degraded
        await barrier.wait()
        async with semaphore:
            started = time.perf_counter()
            try:
                response = await client.post(
                    base + "/api/policy/chat",
                    json={"question": POLICY_QUESTION, "asOf": "2026-10-11"},
                    headers={"X-Tenant-Id": tenant},
                )
                statuses[str(response.status_code)] += 1
                if response.status_code == 429:
                    retry_after.append(response.headers.get("Retry-After", ""))
                elif response.status_code != 200:
                    errors.append({"request": index, "error": f"http_{response.status_code}"})
                else:
                    data = response.json()
                    if data.get("degraded"):
                        degraded += 1
                    retrieval = (data.get("retrieval") or [{}])[0]
                    if retrieval.get("denseDisabled"):
                        dense_degraded += 1
                    if not data.get("runId") or not data.get("clauses"):
                        errors.append({"request": index, "error": "invalid_business_response"})
            except Exception as exc:  # noqa: BLE001
                statuses["transport_error"] += 1
                errors.append({"request": index, "error": type(exc).__name__})
            finally:
                latencies.append((time.perf_counter() - started) * 1000)

    tasks = [asyncio.create_task(one(index)) for index in range(requests)]
    started = time.perf_counter()
    barrier.set()
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - started
    return {
        "tenant": tenant, "requests": requests, "offered_concurrency": concurrency,
        "elapsed_seconds": round(elapsed, 3),
        "http_statuses": dict(statuses),
        "ok": statuses.get("200", 0), "throttled": statuses.get("429", 0),
        "error_count": len(errors), "errors_sample": errors[:10],
        "degraded_count": degraded, "dense_degraded_count": dense_degraded,
        "p50_ms": percentile(latencies, 0.5), "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99), "max_ms": round(max(latencies), 2),
        "retry_after_sample": retry_after[:3],
        "latencies_ms": [round(value, 2) for value in latencies],
    }


def scrape(text: str, metric: str) -> float:
    """汇总 Prometheus 文本中某个指标的全部样本值（标签各不相同则相加）。"""
    total = 0.0
    for line in text.splitlines():
        if not line or line.startswith("#") or not line.startswith(metric):
            continue
        head, _, value = line.rpartition(" ")
        if head.startswith(metric) and (len(head) == len(metric) or head[len(metric)] in "{ "):
            try:
                total += float(value)
            except ValueError:
                continue
    return round(total, 3)


async def run(base: str, token: str, args) -> dict:
    limits = httpx.Limits(max_connections=128, max_keepalive_connections=128)
    async with httpx.AsyncClient(
        timeout=120, limits=limits, trust_env=False,
        headers={
            "X-Internal-Token": token, "X-User-Id": "tenant-benchmark",
            # 生产由网关下发权限；直连压测必须显式声明，否则路由一律 403。
            "X-User-Permissions": "policy:read",
        },
    ) as client:
        await client.post(args.control + "/control/delay", json={"seconds": 0.02})
        isolation_noisy = await fire(
            client, base, tenant="noisy", concurrency=args.isolation_requests,
            requests=args.isolation_requests,
        )
        isolation_quiet = await fire(
            client, base, tenant="quiet", concurrency=args.isolation_requests,
            requests=args.isolation_requests,
        )
        isolation_probe = (await client.get(base + "/benchmark/tenants")).json()

        await client.post(args.control + "/control/delay", json={"seconds": args.capacity_delay})
        capacity_before = (await client.get(base + "/benchmark/tenants")).json()["capacity"]
        # `/metrics` 是 Starlette mount，缺尾斜杠会 307；httpx 默认不跟随重定向，
        # 因此这里必须用带尾斜杠的真实地址，否则抓到的空 body 会算成 0（误导判定）。
        metrics_response = await client.get(base + "/metrics/")
        if metrics_response.status_code != 200:
            raise RuntimeError(f"指标端点不可用：HTTP {metrics_response.status_code}")
        metrics_before = scrape(metrics_response.text, "eaos_capacity_rejected_total")
        capacity = await asyncio.gather(
            fire(client, base, tenant="alpha", concurrency=args.capacity_requests,
                 requests=args.capacity_requests),
            fire(client, base, tenant="beta", concurrency=args.capacity_requests,
                 requests=args.capacity_requests),
        )
        capacity_after = (await client.get(base + "/benchmark/tenants")).json()["capacity"]
        metrics_after = scrape((await client.get(base + "/metrics/")).text, "eaos_capacity_rejected_total")
        capacity_probe = {"before": capacity_before, "after": capacity_after}
        rejected_delta = 0
        for name in set(capacity_before) | set(capacity_after):
            rejected_delta += int(capacity_after.get(name, {}).get("rejected", 0)) - int(
                capacity_before.get(name, {}).get("rejected", 0)
            )

    return {
        "rate_limit_isolation": {
            "noisy": isolation_noisy, "quiet": isolation_quiet, "probe": isolation_probe,
        },
        "capacity_fast_fail": {
            "alpha": capacity[0], "beta": capacity[1],
            "capacity_rejected_delta": rejected_delta,
            "capacity_rejected_metric_delta": round(metrics_after - metrics_before, 3),
            "probe": capacity_probe,
        },
    }


def judge(scenarios: dict, args) -> tuple[bool, list[str]]:
    """判定口径写在代码里，报告与退出码共用，避免"报告绿了但没人知道依据"。"""
    checks: list[tuple[str, bool, str]] = []
    isolation = scenarios["rate_limit_isolation"]
    noisy, quiet = isolation["noisy"], isolation["quiet"]

    checks.append((
        "noisy_tenant_is_throttled",
        noisy["throttled"] >= max(1, args.isolation_requests // 2),
        f"noisy 429={noisy['throttled']} / {noisy['requests']}",
    ))
    checks.append((
        "throttle_response_carries_retry_after",
        bool(noisy["retry_after_sample"]) and all(noisy["retry_after_sample"]),
        f"Retry-After 样本={noisy['retry_after_sample']}",
    ))
    checks.append((
        "quiet_tenant_untouched",
        quiet["throttled"] == 0 and quiet["error_count"] == 0 and quiet["ok"] == quiet["requests"],
        f"quiet 200={quiet['ok']}/{quiet['requests']}, 429={quiet['throttled']}, 错误={quiet['error_count']}",
    ))
    checks.append((
        "quiet_tenant_latency_target",
        quiet["p95_ms"] <= args.quiet_p95_target_ms,
        f"quiet P95={quiet['p95_ms']}ms <= {args.quiet_p95_target_ms}ms",
    ))

    capacity = scenarios["capacity_fast_fail"]
    for tenant in ("alpha", "beta"):
        row = capacity[tenant]
        checks.append((
            f"{tenant}_capacity_returns_200",
            row["ok"] == row["requests"] and row["error_count"] == 0,
            f"{tenant} 200={row['ok']}/{row['requests']}, 错误={row['error_count']}",
        ))
        checks.append((
            f"{tenant}_no_unbounded_queueing",
            row["max_ms"] <= args.capacity_max_ms,
            f"{tenant} max={row['max_ms']}ms <= {args.capacity_max_ms}ms",
        ))
    checks.append((
        "capacity_pool_fast_fails",
        capacity["capacity_rejected_delta"] >= 1,
        f"容量快速失败增量={capacity['capacity_rejected_delta']}",
    ))
    checks.append((
        "degradation_is_marked",
        capacity["alpha"]["dense_degraded_count"] > 0 or capacity["beta"]["dense_degraded_count"] > 0,
        f"dense 降级 alpha={capacity['alpha']['dense_degraded_count']} "
        f"beta={capacity['beta']['dense_degraded_count']}",
    ))
    failures = [f"{name}: {detail}" for name, ok, detail in checks if not ok]
    scenarios["checks"] = [{"name": name, "passed": ok, "detail": detail} for name, ok, detail in checks]
    return not failures, failures


def main() -> None:
    parser = argparse.ArgumentParser(description="G3 多租户资源隔离压测")
    parser.add_argument("--output", default="evals/reports/tenant-isolation-2026-10-25.json")
    parser.add_argument("--startup-timeout", type=int, default=300)
    parser.add_argument("--isolation-requests", type=int, default=12)
    parser.add_argument("--capacity-requests", type=int, default=20)
    parser.add_argument("--capacity-delay", type=float, default=0.6)
    parser.add_argument("--capacity-max-ms", type=float, default=5000.0)
    parser.add_argument("--quiet-p95-target-ms", type=float, default=2000.0)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    fake, fake_port = start_fake_models()
    args.control = f"http://127.0.0.1:{fake_port}"
    report: dict = {}
    server = None
    with tempfile.TemporaryDirectory(prefix="eaos-g3-load-", ignore_cleanup_errors=True) as directory:
        temporary = Path(directory)
        token = secrets.token_hex(24)
        env = os.environ.copy()
        env.update({
            "DATABASE_URL": "sqlite:///" + (temporary / "tenants.sqlite").as_posix(),
            "APP_ENV": "test", "AI_INTERNAL_TOKEN": token,
            "EXPORT_DIR": str(temporary / "exports"), "UPLOAD_DIR": str(temporary / "uploads"),
            "PYTHONUTF8": "1", "CELERY_ENABLED": "false",
            # 离线生成模型：本项只验证资源隔离，不调用付费 LLM
            "LLM_API_KEY": "",
            # 指向本地假模型：可动态调慢，用于制造 Embedding / Rerank 容量饱和
            "EMBEDDING_API_KEY": "local-fake", "EMBEDDING_MODEL": "local-fake-embedding-64",
            "EMBEDDING_BASE_URL": f"http://127.0.0.1:{fake_port}/v1",
            "EMBEDDING_DIMENSIONS": "64", "EMBEDDING_TIMEOUT": "20", "EMBEDDING_BATCH_SIZE": "8",
            "RERANK_URL": f"http://127.0.0.1:{fake_port}/v1/rerank", "RERANK_API_KEY": "local-fake",
            "RERANK_MODEL": "local-fake-rerank", "RERANK_TIMEOUT": "20", "RERANK_LOCAL_MODEL": "",
            # 耗时链路容量：故意收紧，让"快速失败"成为可观测事实
            "EMBEDDING_POOL_WORKERS": "2", "EMBEDDING_POOL_QUEUE": "2",
            "RERANK_POOL_WORKERS": "1", "RERANK_POOL_QUEUE": "1",
            "LLM_POOL_WORKERS": "2", "LLM_POOL_QUEUE": "2",
            # 租户限流：noisy 被压到 rps=2/burst=4；其余租户用全局默认
            "RATE_LIMIT_ENABLED": "true",
            "RATE_LIMIT_RPS": "100", "RATE_LIMIT_BURST": "200",
            "RATE_LIMIT_MAX_CONCURRENCY": "0", "RATE_LIMIT_GLOBAL_CONCURRENCY": "0",
            "RATE_LIMIT_TENANT_OVERRIDES": json.dumps(
                {"noisy": {"rps": 2, "burst": 4, "concurrency": 0}}
            ),
            "RATE_LIMIT_AUDIT_ENABLED": "false",
        })
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        with output.with_suffix(".log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "evals.benchmark_app:app",
                 "--host", "127.0.0.1", "--port", str(port), "--backlog", "2048", "--no-access-log"],
                cwd=ROOT, env=env, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                ready = False
                deadline = time.monotonic() + args.startup_timeout
                with httpx.Client(timeout=2, trust_env=False) as client:
                    while time.monotonic() < deadline:
                        if server.poll() is not None:
                            break
                        try:
                            ready = client.get(base + "/api/health").status_code == 200
                        except httpx.HTTPError:
                            pass
                        if ready:
                            break
                        time.sleep(0.25)
                if not ready:
                    raise RuntimeError(f"压测服务启动失败，见 {output.with_suffix('.log')}")
                report = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "kind": "g3-tenant-resource-isolation",
                    "synthetic": True, "database": "isolated-temporary-sqlite",
                    "server_workers": 1, "platform": platform.platform(), "logical_cpus": os.cpu_count(),
                    "scope": "Python AI service only; excludes Java gateway/JWT/production PostgreSQL/"
                             "external network and real model quota",
                    "model_backend": "offline mock LLM + local fake embedding/rerank with tunable latency",
                    "tenant_quota": {"noisy": {"rps": 2, "burst": 4}, "default": {"rps": 100, "burst": 200}},
                    "capacity_pool": {"embedding": {"workers": 2, "queue": 2},
                                      "rerank": {"workers": 1, "queue": 1}},
                    "production_accepted": False,
                    "scenarios": {}, "checks": [], "failures": [], "passed": False, "completed": False,
                }
                scenarios = asyncio.run(run(base, token, args))
                passed, failures = judge(scenarios, args)
                report.update(
                    scenarios=scenarios,
                    checks=scenarios.pop("checks", []),
                    failures=failures, passed=passed, completed=True,
                )
                output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
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
    print(json.dumps({k: report.get(k) for k in ("passed", "failures", "checks")},
                     ensure_ascii=False, indent=2), flush=True)
    raise SystemExit(0 if report.get("passed") else 1)


if __name__ == "__main__":
    main()