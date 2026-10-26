"""Real HTTP load against an owned, temporary single-worker service."""
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
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, p):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * p) - 1)], 2)


async def scenario(client, base, domain, concurrency, count):
    path = "/api/policy/chat" if domain == "policy" else "/api/drafts/news"
    payload = (
        {"question": "研发补助申请需要什么材料？", "asOf": "2026-10-11"}
        if domain == "policy" else {
            "title": "项目启动会新闻稿", "template": "news_release", "style": "正式",
            "eventDesc": "测试公司于2026年10月11日召开项目启动会。",
            "keyFacts": [{"name": "发布日期", "value": "2026年10月11日"}],
        }
    )
    semaphore = asyncio.Semaphore(concurrency)
    barrier = asyncio.Event()
    latencies, errors, statuses = [], [], Counter()
    active, peak = 0, 0

    async def request_one(index):
        nonlocal active, peak
        await barrier.wait()
        async with semaphore:
            active += 1
            peak = max(peak, active)
            started = time.perf_counter()
            try:
                response = await client.post(base + path, json=payload)
                statuses[str(response.status_code)] += 1
                if response.status_code != 200:
                    errors.append({"request": index, "error": f"http_{response.status_code}"})
                else:
                    data = response.json()
                    if not data.get("runId") or not (
                        data.get("clauses") and data.get("answer") if domain == "policy"
                        else data.get("versionId") and data.get("draft") and data.get("factCheckReport")
                    ):
                        errors.append({"request": index, "error": "invalid_business_response"})
            except Exception as exc:
                statuses["transport_error"] += 1
                errors.append({"request": index, "error": type(exc).__name__})
            finally:
                latencies.append((time.perf_counter() - started) * 1000)
                active -= 1

    await client.get(base + "/benchmark/concurrency")
    tasks = [asyncio.create_task(request_one(i)) for i in range(count)]
    started = time.perf_counter()
    barrier.set()
    await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - started
    try:
        server = (await client.get(base + "/benchmark/concurrency", timeout=5)).json()
    except (httpx.HTTPError, ValueError):
        server = {"peak_server_inflight": None, "probe_error": True}
    target = 2000 if domain == "policy" else 30000
    p95 = percentile(latencies, 0.95)
    return {
        "domain": domain, "requests": count, "offered_concurrency": concurrency,
        "peak_client_inflight": peak, **server, "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(count / elapsed, 2), "http_statuses": dict(statuses),
        "error_count": len(errors), "error_rate": len(errors) / count,
        "p50_ms": percentile(latencies, 0.5), "p95_ms": p95,
        "p99_ms": percentile(latencies, 0.99), "max_ms": round(max(latencies), 2),
        "latency_target_ms": target, "p95_target_met": p95 <= target,
        "all_requests_target_met": max(latencies) <= target,
        "passed": not errors and p95 <= target,
        "errors_sample": errors[:20],
    }


async def run(base, token, levels, requests, checkpoint):
    limits = httpx.Limits(max_connections=max(levels), max_keepalive_connections=max(levels))
    async with httpx.AsyncClient(
        timeout=180, limits=limits, trust_env=False,
        headers={
            "X-Internal-Token": token, "X-User-Id": "benchmark-author",
            # 网关在生产上按路由下发权限；压测直连服务必须显式声明，否则一律 403。
            "X-User-Permissions": "policy:read,draft:write",
        },
    ) as client:
        scenarios = []
        for level in levels:
            for domain in ("policy", "announcement"):
                row = await scenario(client, base, domain, level, max(level, requests))
                scenarios.append(row)
                checkpoint(scenarios)
                print(json.dumps(row, ensure_ascii=False), flush=True)
        return scenarios


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--allow-model-cost", action="store_true")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 50, 500])
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--startup-timeout", type=int, default=180)
    parser.add_argument("--output", default="evals/reports/load-offline-2026-10-11.json")
    args = parser.parse_args()
    if args.mode == "live" and not args.allow_model_cost:
        parser.error("Live load invokes paid models; explicitly pass --allow-model-cost")
    if any(level < 1 or level > 2000 for level in args.concurrency) or args.requests < 1:
        parser.error("Concurrency must be 1..2000 and requests must be positive")
    if args.startup_timeout < 1:
        parser.error("Startup timeout must be positive")
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eaos-p0-load-", ignore_cleanup_errors=True) as directory:
        temporary = Path(directory)
        env = os.environ.copy()
        token = secrets.token_hex(24)
        env.update({
            "DATABASE_URL": "sqlite:///" + (temporary / "benchmark.sqlite").as_posix(),
            "APP_ENV": "test", "AI_INTERNAL_TOKEN": token,
            "EXPORT_DIR": str(temporary / "exports"), "UPLOAD_DIR": str(temporary / "uploads"),
            "PYTHONUTF8": "1", "CELERY_ENABLED": "false",
            # 容量测试测的是系统极限，不是限流行为：租户限流显式关闭，
            # 多租户隔离另有 evals.tenant_load_test 专门验证。
            "RATE_LIMIT_ENABLED": "false",
        })
        if args.mode == "offline":
            env.update({name: "" for name in ("LLM_API_KEY", "EMBEDDING_API_KEY", "RERANK_URL", "RERANK_LOCAL_MODEL")})
        else:
            from app.config import settings
            if not (settings.llm_api_key and settings.embedding_api_key and (settings.rerank_url or settings.rerank_local_model)):
                parser.error("Live load requires LLM, Dense and semantic reranker configuration")
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
                startup_deadline = time.monotonic() + args.startup_timeout
                with httpx.Client(timeout=1, trust_env=False) as client:
                    while time.monotonic() < startup_deadline:
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
                    raise RuntimeError(f"Benchmark service failed to start; see {output.with_suffix('.log')}")
                report = {
                    "generated_at": datetime.now(timezone.utc).isoformat(), "mode": args.mode,
                    "synthetic": True, "database": "isolated-temporary-sqlite",
                    "server_workers": 1, "platform": platform.platform(), "logical_cpus": os.cpu_count(),
                    "scope": "Python HTTP service only; excludes Java/JWT/network/gateway and external production data",
                    "model_backend": "offline mock + hash Dense + lexical rerank" if args.mode == "offline" else "configured-live",
                    "tenant_rate_limit": "disabled-for-capacity-test",
                    "production_accepted": False, "availability_99_9_verified": False,
                    "scenarios": [], "passed": False, "completed": False,
                }
                def checkpoint(scenarios):
                    report["scenarios"] = scenarios
                    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                scenarios = asyncio.run(run(base, token, args.concurrency, args.requests, checkpoint))
                report.update(passed=all(row["passed"] for row in scenarios), completed=True)
                checkpoint(scenarios)
            finally:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], capture_output=True)
                else:
                    server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=15)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
