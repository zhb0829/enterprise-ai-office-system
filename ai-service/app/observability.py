"""可观测性（Q13）：Prometheus 指标 + traceId 日志贯通。

- HTTP 请求计数/延迟直方图（含 5xx 统计）
- LLM 调用计数/延迟（供 Grafana 告警 P95 超时）
- X-Trace-Id 中间件：从 Java 网关透传或自动生成，写入 contextvar 供日志与响应头使用
"""
import logging
import time
import uuid
from contextvars import ContextVar

from prometheus_client import Counter, Histogram, make_asgi_app

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

REQUEST_COUNT = Counter(
    "eaos_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "eaos_http_request_seconds", "HTTP request latency", ["method", "path"]
)
LLM_CALLS = Counter("eaos_llm_calls_total", "LLM calls", ["model", "result"])
LLM_LATENCY = Histogram("eaos_llm_call_seconds", "LLM call latency", ["model"])


class TraceIdLogFilter(logging.Filter):
    """把当前请求的 traceId 注入每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get()
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(trace_id)s] %(name)s - %(message)s"
        )
    )
    handler.addFilter(TraceIdLogFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def observe_llm(model: str):
    """LLM 调用计时装饰器上下文：with observe_llm(model).measure(): ..."""

    class _Timer:
        def __enter__(self):
            self.start = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc, tb):
            duration = time.perf_counter() - self.start
            result = "error" if exc else "ok"
            LLM_CALLS.labels(model=model, result=result).inc()
            LLM_LATENCY.labels(model=model).observe(duration)
            return False

    return _Timer()


def install_observability(app) -> None:
    """挂载 /metrics 与 traceId/指标中间件。"""

    @app.middleware("http")
    async def observability_middleware(request, call_next):
        incoming = request.headers.get("x-trace-id") or uuid.uuid4().hex[:16]
        token = trace_id_var.set(incoming)
        method = request.method
        path = request.url.path
        start = time.perf_counter()
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception:
            status = 500
            REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
            REQUEST_LATENCY.labels(method=method, path=path).observe(
                time.perf_counter() - start
            )
            trace_id_var.reset(token)
            raise
        response.headers["X-Trace-Id"] = incoming
        REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
        REQUEST_LATENCY.labels(method=method, path=path).observe(
            time.perf_counter() - start
        )
        trace_id_var.reset(token)
        return response

    app.mount("/metrics", make_asgi_app())
