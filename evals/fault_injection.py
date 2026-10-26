"""G5 故障注入验收：关掉图谱 / 精排 / 远端模型 / 交叉验证后，服务仍须正常返回并标记降级。

做法：起一个自建、临时 SQLite 的单 worker 服务，模型指向本地假服务（可远程返回 500），
然后**不重启进程**，只经 `/api/agent/flags` 热切换开关，逐项断言：

| 注入 | 期望 |
|---|---|
| 关闭 `remote_llm` | 200 + `degraded` + "运行时开关已关闭外部生成模型"；恢复后立刻回到未降级 |
| 关闭 `remote_embedding` | 200 + `denseBackend=disabled-by-flag`（不混用哈希向量） |
| 关闭 `semantic_rerank` | 200 + `deterministic-lexical` + `runtime-flag-semantic-rerank-off` |
| 关闭 `kg` | 200 + `fusionSources` 不含 graph + 明确降级说明 |
| 关闭 `factcheck` | 200 + `factCheckReport` 每条 `degraded=true` |
| 远端精排真实返回 500 | 200 + 词法降级 + `reranker.degraded=true` |

同时比对 `/benchmark/identity` 的进程 token，证明整轮注入期间**进程没有重启**。
边界：只覆盖 Python AI 服务；真实网关、生产库与真实模型配额仍需预生产环境验收。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import secrets
import socket
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
QUESTION = "研发补助申请需要什么材料？"
FLAG_NAMES = ("kg", "semantic_rerank", "remote_llm", "remote_embedding", "factcheck")
NEWS_PAYLOAD = {
    "title": "项目启动会新闻稿", "template": "news_release", "style": "正式",
    "eventDesc": "测试公司于2026年10月11日召开项目启动会。",
    "keyFacts": [{"name": "发布日期", "value": "2026年10月11日"}],
}
DRAFT_TEXT = "公司于2026年10月11日召开项目启动会，会议由总经理主持。"


# ===== 本地假模型服务：可切慢、可切 500，用于故障注入 =====

class _FakeModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    rerank_status = 200

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

    def _send_stream(self, pieces: list[str]) -> None:
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for piece in pieces:
                chunk = {
                    "id": "chatcmpl-local", "object": "chat.completion.chunk", "created": 0,
                    "model": "local-fake-chat",
                    "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
                }
                self._write_chunk("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n")
            tail = {
                "id": "chatcmpl-local", "object": "chat.completion.chunk", "created": 0,
                "model": "local-fake-chat",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 20, "total_tokens": 32},
            }
            self._write_chunk("data: " + json.dumps(tail, ensure_ascii=False) + "\n\n")
            self._write_chunk("data: [DONE]\n\n")
            self.wfile.write(b"0\r\n\r\n")
        except (ConnectionError, OSError):
            return

    def _write_chunk(self, text: str) -> None:
        data = text.encode("utf-8")
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n")

    def do_POST(self):  # noqa: N802  http.server 约定
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}
        if self.path.endswith("/control/rerank-status"):
            _FakeModelHandler.rerank_status = int(payload.get("status") or 200)
            return self._send({"rerank_status": _FakeModelHandler.rerank_status})
        if self.path.endswith("/chat/completions"):
            if payload.get("stream"):
                return self._send_stream([DRAFT_TEXT[index:index + 8] for index in range(0, len(DRAFT_TEXT), 8)])
            content = json.dumps(
                {"answer": f"申请研发补助需要提交研发费用归集表等材料[引用1]。", "usedCitations": [1]},
                ensure_ascii=False,
            )
            return self._send({
                "id": "chatcmpl-local", "object": "chat.completion", "created": 0,
                "model": "local-fake-chat",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
            })
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
            if _FakeModelHandler.rerank_status >= 400:
                return self._send({"detail": "injected rerank failure"},
                                  status=_FakeModelHandler.rerank_status)
            documents = payload.get("documents") or []
            return self._send({"results": [
                {"index": index, "relevance_score": round(1.0 - index * 0.01, 4)}
                for index in range(len(documents))
            ]})
        return self._send({"detail": "not found"}, status=404)


class _FakeModelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):  # noqa: D102
        return


def start_fake_models() -> tuple[_FakeModelServer, int]:
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


def degradation_text(payload: dict) -> str:
    return " ".join(payload.get("degradationReasons") or [])


async def set_flag(client, base, headers, name: str, value) -> httpx.Response:
    return await client.put(
        base + f"/api/agent/flags/{name}",
        json={"enabled": value, "reason": "G5 故障注入验收"},
        headers=headers,
    )


async def reset_flags(client, base, headers) -> None:
    for name in FLAG_NAMES:
        await set_flag(client, base, headers, name, None)


async def policy_chat(client, base, headers) -> httpx.Response:
    return await client.post(
        base + "/api/policy/chat",
        json={"question": QUESTION, "asOf": "2026-10-11"},
        headers=headers,
    )


async def run(base: str, token: str, report: Report) -> dict:
    headers = {
        "X-Internal-Token": token, "X-User-Id": "fault-injection-ops",
        "X-Tenant-Id": "default",
        "X-User-Permissions": "policy:read,draft:write,agent:audit,agent:admin",
    }
    limits = httpx.Limits(max_connections=32, max_keepalive_connections=32)
    async with httpx.AsyncClient(timeout=120, limits=limits, trust_env=False) as client:
        started_identity = (await client.get(base + "/benchmark/identity")).json()

        # 0) 基线：模型可用、无开关关闭 → 不得声称降级
        await reset_flags(client, base, headers)
        baseline = await policy_chat(client, base, headers)
        body = baseline.json() if baseline.status_code == 200 else {}
        report.scenario("baseline", {
            "status": baseline.status_code, "degraded": body.get("degraded"),
            "reasons": body.get("degradationReasons"), "clauses": len(body.get("clauses") or []),
        })
        report.check("baseline_ok", baseline.status_code == 200, f"HTTP {baseline.status_code}")
        report.check("baseline_not_degraded", body.get("degraded") is False,
                     f"degraded={body.get('degraded')} reasons={body.get('degradationReasons')}")

        # 1) 关闭外部生成模型：不得调用远端，退化为检索兜底并标记降级
        assert (await set_flag(client, base, headers, "remote_llm", False)).status_code == 200
        response = await policy_chat(client, base, headers)
        body = response.json()
        report.scenario("remote_llm_off", {
            "status": response.status_code, "degraded": body.get("degraded"),
            "reasons": body.get("degradationReasons"), "model": body.get("model"),
        })
        report.check("remote_llm_off_returns_200", response.status_code == 200, f"HTTP {response.status_code}")
        report.check("remote_llm_off_marked", body.get("degraded") is True
                     and "运行时开关已关闭外部生成模型" in degradation_text(body),
                     f"reasons={body.get('degradationReasons')}")
        report.check("remote_llm_off_still_answers", bool(body.get("answer")) and bool(body.get("clauses")),
                     f"answer_len={len(body.get('answer') or '')} clauses={len(body.get('clauses') or [])}")

        # 1b) 恢复开关：秒级回切，无需重启
        assert (await set_flag(client, base, headers, "remote_llm", None)).status_code == 200
        recovered = await policy_chat(client, base, headers)
        recovered_body = recovered.json()
        report.scenario("remote_llm_restored", {
            "status": recovered.status_code, "degraded": recovered_body.get("degraded"),
            "reasons": recovered_body.get("degradationReasons"),
        })
        report.check("remote_llm_restore_is_live",
                     recovered.status_code == 200 and recovered_body.get("degraded") is False,
                     f"HTTP {recovered.status_code} degraded={recovered_body.get('degraded')}")

        # 2) 关闭外部向量模型：跳过 Dense 路，且不得混用哈希向量
        assert (await set_flag(client, base, headers, "remote_embedding", False)).status_code == 200
        response = await policy_chat(client, base, headers)
        body = response.json()
        retrieval = (body.get("retrieval") or [{}])[0]
        report.scenario("remote_embedding_off", {
            "status": response.status_code, "degraded": body.get("degraded"),
            "denseBackend": retrieval.get("denseBackend"), "denseDisabled": retrieval.get("denseDisabled"),
            "runtimeFlags": retrieval.get("runtimeFlags"), "reasons": body.get("degradationReasons"),
        })
        report.check("remote_embedding_off_returns_200", response.status_code == 200, f"HTTP {response.status_code}")
        report.check("remote_embedding_off_skips_dense",
                     retrieval.get("denseBackend") == "disabled-by-flag"
                     and retrieval.get("denseDisabled") is True
                     and "remote_embedding" in (retrieval.get("runtimeFlags") or []),
                     f"denseBackend={retrieval.get('denseBackend')} flags={retrieval.get('runtimeFlags')}")
        await set_flag(client, base, headers, "remote_embedding", None)

        # 3) 关闭语义精排：退化为确定性词法重排并标记原因
        assert (await set_flag(client, base, headers, "semantic_rerank", False)).status_code == 200
        response = await policy_chat(client, base, headers)
        body = response.json()
        retrieval = (body.get("retrieval") or [{}])[0]
        reranker = retrieval.get("reranker") or {}
        report.scenario("semantic_rerank_off", {
            "status": response.status_code, "degraded": body.get("degraded"), "reranker": reranker,
            "reasons": body.get("degradationReasons"),
        })
        report.check("semantic_rerank_off_returns_200", response.status_code == 200, f"HTTP {response.status_code}")
        report.check("semantic_rerank_off_degrades",
                     reranker.get("backend") == "deterministic-lexical"
                     and reranker.get("reason") == "runtime-flag-semantic-rerank-off"
                     and body.get("degraded") is True,
                     f"reranker={reranker}")
        await set_flag(client, base, headers, "semantic_rerank", None)

        # 4) 远端精排真实故障（HTTP 500）由 main() 在全部开关场景跑完后单独注入，
        #    保证"上游真的坏了"与"运维关掉开关"两种降级路径互不混淆。

        # 5) 关闭图谱：默认 KG_ENABLED=true，关闭后不得再走图路
        assert (await set_flag(client, base, headers, "kg", False)).status_code == 200
        response = await policy_chat(client, base, headers)
        body = response.json()
        retrieval = (body.get("retrieval") or [{}])[0]
        report.scenario("kg_off", {
            "status": response.status_code, "degraded": body.get("degraded"),
            "fusionSources": retrieval.get("fusionSources"), "graph": retrieval.get("graph"),
            "reasons": body.get("degradationReasons"),
        })
        report.check("kg_off_returns_200", response.status_code == 200, f"HTTP {response.status_code}")
        report.check("kg_off_skips_graph",
                     "graph" not in (retrieval.get("fusionSources") or [])
                     and "图谱召回已被运行时开关关闭" in degradation_text(body),
                     f"sources={retrieval.get('fusionSources')} reasons={body.get('degradationReasons')}")
        await set_flag(client, base, headers, "kg", None)

        # 6) 关闭模型事实核查：公告链路仍出稿，但每条核查标记降级
        assert (await set_flag(client, base, headers, "factcheck", False)).status_code == 200
        news = await client.post(base + "/api/drafts/news", json=NEWS_PAYLOAD, headers=headers)
        news_body = news.json() if news.status_code == 200 else {}
        items = news_body.get("factCheckReport") or []
        report.scenario("factcheck_off", {
            "status": news.status_code, "items": len(items),
            "degraded_items": sum(1 for item in items if item.get("degraded")),
            "reason_sample": items[0].get("degradeReason") if items else None,
        })
        report.check("factcheck_off_returns_200", news.status_code == 200, f"HTTP {news.status_code}")
        report.check("factcheck_off_marks_every_claim",
                     bool(items) and all(item.get("degraded") is True for item in items)
                     and all(item.get("degradeReason") == "runtime-flag-factcheck-off" for item in items),
                     f"items={len(items)} degraded={sum(1 for item in items if item.get('degraded'))}")

        # 6b) 恢复核查开关
        assert (await set_flag(client, base, headers, "factcheck", None)).status_code == 200
        news = await client.post(base + "/api/drafts/news", json=NEWS_PAYLOAD, headers=headers)
        news_body = news.json() if news.status_code == 200 else {}
        items = news_body.get("factCheckReport") or []
        report.scenario("factcheck_restored", {
            "status": news.status_code, "items": len(items),
            "degraded_items": sum(1 for item in items if item.get("degraded")),
        })
        report.check("factcheck_restore_is_live",
                     news.status_code == 200 and not any(item.get("degraded") for item in items),
                     f"HTTP {news.status_code} degraded={sum(1 for item in items if item.get('degraded'))}")

        # 7) 全程进程未重启：进程身份 token 必须不变（重启会换 token）
        finished_identity = (await client.get(base + "/benchmark/identity")).json()
        report.scenario("process_identity", {
            "before": started_identity, "after": finished_identity,
        })
        report.check("no_restart_during_injection",
                     started_identity.get("processToken") == finished_identity.get("processToken")
                     and bool(started_identity.get("processToken")),
                     f"pid={started_identity.get('pid')} "
                     f"uptime={finished_identity.get('uptimeSeconds')}s "
                     f"token_stable={started_identity.get('processToken') == finished_identity.get('processToken')}")

        flags = (await client.get(base + "/api/agent/flags", headers=headers)).json()
    return flags


def main() -> None:
    parser = argparse.ArgumentParser(description="G5 运行时开关故障注入验收")
    parser.add_argument("--output", default="evals/reports/fault-injection-2026-10-25.json")
    parser.add_argument("--startup-timeout", type=int, default=300)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    fake, fake_port = start_fake_models()
    report = Report()
    payload: dict = {}
    server = None
    with tempfile.TemporaryDirectory(prefix="eaos-g5-fault-", ignore_cleanup_errors=True) as directory:
        temporary = Path(directory)
        token = secrets.token_hex(24)
        env = os.environ.copy()
        env.update({
            "DATABASE_URL": "sqlite:///" + (temporary / "fault.sqlite").as_posix(),
            "APP_ENV": "test", "AI_INTERNAL_TOKEN": token,
            "EXPORT_DIR": str(temporary / "exports"), "UPLOAD_DIR": str(temporary / "uploads"),
            "PYTHONUTF8": "1", "CELERY_ENABLED": "false",
            # 全部模型指向本地假服务（可注入 500），基线因此不是"没配模型"而是"模型可用"
            "LLM_API_KEY": "local-fake", "LLM_BASE_URL": f"http://127.0.0.1:{fake_port}/v1",
            "LLM_MODEL_GENERATION": "local-fake-chat", "LLM_MODEL_EXTRACTION": "local-fake-chat",
            "LLM_MODEL_FACTCHECK": "local-fake-chat", "LLM_TIMEOUT": "20",
            "EMBEDDING_API_KEY": "local-fake", "EMBEDDING_MODEL": "local-fake-embedding-64",
            "EMBEDDING_BASE_URL": f"http://127.0.0.1:{fake_port}/v1",
            "EMBEDDING_DIMENSIONS": "64", "EMBEDDING_TIMEOUT": "20", "EMBEDDING_BATCH_SIZE": "8",
            "RERANK_URL": f"http://127.0.0.1:{fake_port}/v1/rerank", "RERANK_API_KEY": "local-fake",
            "RERANK_MODEL": "local-fake-rerank", "RERANK_TIMEOUT": "20", "RERANK_LOCAL_MODEL": "",
            # 图谱在配置上开启：这样"关闭开关"才是有意义的注入
            "KG_ENABLED": "true",
            "RATE_LIMIT_ENABLED": "false",
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
                    raise RuntimeError(f"故障注入服务启动失败，见 {output.with_suffix('.log')}")

                # 远端精排注入 500：在跑业务场景前先让假服务进入故障态由场景 4 触发
                async def prepare() -> dict:
                    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
                        return (await client.post(
                            f"http://127.0.0.1:{fake_port}/control/rerank-status", json={"status": 200},
                        )).json()

                asyncio.run(prepare())
                flags = asyncio.run(run(base, token, report))
                # 场景 4 需要真实 500：单独触发一次（保持其它场景干净）
                async def inject_and_check() -> None:
                    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                        await client.post(f"http://127.0.0.1:{fake_port}/control/rerank-status",
                                          json={"status": 500})
                        headers = {
                            "X-Internal-Token": token, "X-User-Id": "fault-injection-ops",
                            "X-Tenant-Id": "default",
                            "X-User-Permissions": "policy:read,agent:admin",
                        }
                        for name in FLAG_NAMES:
                            await client.put(base + f"/api/agent/flags/{name}",
                                             json={"enabled": None, "reason": "恢复"}, headers=headers)
                        response = await client.post(base + "/api/policy/chat",
                                                     json={"question": QUESTION, "asOf": "2026-10-11"},
                                                     headers=headers)
                        body = response.json()
                        retrieval = (body.get("retrieval") or [{}])[0]
                        reranker = retrieval.get("reranker") or {}
                        report.scenario("rerank_remote_500", {
                            "status": response.status_code, "degraded": body.get("degraded"),
                            "reranker": reranker,
                        })
                        report.check("rerank_remote_500_returns_200", response.status_code == 200,
                                     f"HTTP {response.status_code}")
                        report.check("rerank_remote_500_degrades",
                                     reranker.get("degraded") is True
                                     and reranker.get("backend") == "deterministic-lexical",
                                     f"reranker={reranker}")

                asyncio.run(inject_and_check())
                failures = [item for item in report.checks if not item["passed"]]
                payload = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "kind": "g5-runtime-flag-fault-injection",
                    "synthetic": True, "database": "isolated-temporary-sqlite",
                    "server_workers": 1, "platform": platform.platform(),
                    "scope": "Python AI service only; excludes Java gateway/JWT/production "
                             "PostgreSQL and real model quota",
                    "model_backend": "local fake LLM/Embedding/Rerank (rerank can inject HTTP 500)",
                    "flags": flags.get("flags"),
                    "process_restarted": False,
                    "scenarios": report.scenarios, "checks": report.checks,
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
    print(json.dumps({"passed": payload.get("passed"), "failures": payload.get("failures"),
                      "checks": payload.get("checks")}, ensure_ascii=False, indent=2), flush=True)
    raise SystemExit(0 if payload.get("passed") else 1)


if __name__ == "__main__":
    main()