"""可观测性（Q13）：Prometheus 指标 + traceId 日志贯通。

- HTTP 请求计数/延迟直方图（含 5xx 统计）
- LLM 调用计数/延迟（供 Grafana 告警 P95 超时）
- X-Trace-Id 中间件：从 Java 网关透传或自动生成，写入 contextvar 供日志与响应头使用
"""
import logging
import time
import uuid
from contextvars import ContextVar

import prometheus_client
from prometheus_client import Counter, Histogram, make_asgi_app

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
user_id_var: ContextVar[str] = ContextVar("agent_user_id", default="")


def _metric(factory, *args, **kwargs):
    """幂等注册：模块被重复导入（如 pytest 收集）时不抛 DuplicateTimeseries。"""
    try:
        return factory(*args, **kwargs)
    except ValueError:
        name = kwargs.get("name") or (args[0] if args else "")
        collector = prometheus_client.REGISTRY._names_to_collectors.get(name)
        if collector is None:
            raise
        return collector


REQUEST_COUNT = _metric(
    Counter, "eaos_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = _metric(
    Histogram, "eaos_http_request_seconds", "HTTP request latency", ["method", "path"]
)
LLM_CALLS = _metric(Counter, "eaos_llm_calls_total", "LLM calls", ["model", "result"])
LLM_LATENCY = _metric(Histogram, "eaos_llm_call_seconds", "LLM call latency", ["model"])


class TraceIdLogFilter(logging.Filter):
    """把当前请求的 traceId 注入每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        import traceback
        from .agent.governance import redact
        record.trace_id = trace_id_var.get()
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)))
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
        import re
        from .config import settings
        import hmac
        from .agent.governance import DataLevel, Principal, principal_var, data_level_var

        supplied = request.headers.get("x-trace-id", "")
        incoming = supplied if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", supplied) else uuid.uuid4().hex
        token = trace_id_var.set(incoming)
        trusted = bool(settings.ai_internal_token) and hmac.compare_digest(
            request.headers.get("x-internal-token", ""), settings.ai_internal_token
        )
        # G7：租户治理角色只认受信网关下发的头；客户端伪造 X-User-Role 在 Java 侧被剥离，
        # 这里再以内部令牌为前提读取，双重前提才成立。
        from .agent.access import ROLE_HEADER, harden_principal, normalize_role
        # 同一个受信身份头出现多次 = 头走私风险（网关应覆盖而不是追加），直接 fail-closed。
        duplicated_headers = [
            name for name in ("x-user-role", "x-user-permissions", "x-user-id", "x-tenant-id")
            if len(request.headers.getlist(name)) > 1
        ]
        role = normalize_role(request.headers.get(ROLE_HEADER, "")) if trusted else ""
        # 角色治理只覆盖对外面；/internal/**（服务间调用）与 /metrics 不受角色判定影响，
        # 否则网关一旦给内部请求补角色头、又没带租户身份，内部链路会被误伤成 403。
        user_token = user_id_var.set(request.headers.get("x-user-id", "")[:64] if trusted else "")
        clearance = request.headers.get("x-data-clearance", "internal")
        identity = Principal(
            user_id=user_id_var.get(),
            tenant_id=request.headers.get("x-tenant-id", "default")[:64] if trusted else "",
            department_id=request.headers.get("x-department-id", "")[:64] if trusted else "",
            permissions=frozenset(p.strip() for p in request.headers.get("x-user-permissions", "").split(",") if p.strip()) if trusted else frozenset(),
            clearance=DataLevel.__members__.get(clearance, DataLevel.public) if trusted else DataLevel.public,
            public_only=request.headers.get("x-public-only", "false").lower() != "false" if trusted else True,
            role=role,
        )
        principal_token = principal_var.set(identity)
        data_token = data_level_var.set(DataLevel.public)
        method = request.method
        path = request.url.path
        start = time.perf_counter()
        permission = ""

        async def persist_http_audit(status):
            if not path.startswith(("/api/", "/static/")) or path == "/api/health":
                return
            from starlette.concurrency import run_in_threadpool
            from . import db as app_db
            from .agent.governance import audit
            def persist():
                try:
                    with app_db.SessionLocal() as db:
                        audit(db, f"http.{method.lower()}", path,
                              outcome="allowed" if status < 400 else "denied" if status in {401, 403} else "failed",
                              details={"status": status, "permission": permission, "role": identity.role or "legacy"}, principal=identity)
                        db.commit()
                except Exception:
                    logging.getLogger("governance.audit").exception("HTTP audit persistence failed")
            await run_in_threadpool(persist)

        try:
            from .agent.governance import require_route_permission
            from fastapi import HTTPException
            from fastapi.responses import JSONResponse
            try:
                if method == "OPTIONS":
                    # CORS 预检不携带业务语义：必须让路给内层 CORSMiddleware，不能死在权限校验上。
                    response = await call_next(request)
                elif duplicated_headers:
                    raise HTTPException(403, f"duplicated trusted identity header: {duplicated_headers[0]}")
                elif (settings.tenant_role_required and trusted and path.startswith(("/api/", "/static/"))
                      and not identity.role):
                    # 收口模式：网关全量下发角色头后打开，避免"漏发角色头 = 静默沿用未收敛权限"。
                    raise HTTPException(403, "X-User-Role is required for external API requests")
                else:
                    if trusted and path.startswith(("/api/", "/static/")):
                        # G7 网关第一跳：未知角色 / 缺租户身份直接 403；声明角色后权限按角色基线收敛。
                        hardened = harden_principal(identity)
                        if hardened is not identity:
                            principal_var.reset(principal_token)
                            principal_token = principal_var.set(hardened)
                            identity = hardened
                    resource = request.headers.get("x-download-resource", "") if trusted else ""
                    if resource and path.startswith("/static/uploads/"):
                        identity.require("opinion:read")
                        permission = "opinion:read"
                    else:
                        permission = require_route_permission(path, method)
                    if path.startswith(("/static/uploads/", "/static/exports/")):
                        from starlette.concurrency import run_in_threadpool
                        from .agent.governance import authorize_download
                        from . import db as app_db
                        def check_download():
                            with app_db.SessionLocal() as db:
                                authorize_download(db, path, resource)
                        await run_in_threadpool(check_download)
                    response = await call_next(request)
            except HTTPException as exc:
                detail = str(exc.detail)
                permission = detail if ("permission required" in detail or "role baseline" in detail) else f"identity-check:{exc.status_code}"
                response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            status = response.status_code
            if permission:
                logging.getLogger("governance.audit").info(
                    "action=http.%s resource=%s user=%s tenant=%s permission=%s outcome=%s",
                    method.lower(), getattr(request.scope.get("route"), "path", "/unmatched"),
                    identity.user_id, identity.tenant_id, permission, status,
                )
            await persist_http_audit(status)
        except Exception:
            status = 500
            await persist_http_audit(status)
            path = getattr(request.scope.get("route"), "path", "/unmatched")
            REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
            REQUEST_LATENCY.labels(method=method, path=path).observe(
                time.perf_counter() - start
            )
            trace_id_var.reset(token)
            user_id_var.reset(user_token)
            principal_var.reset(principal_token)
            data_level_var.reset(data_token)
            raise
        response.headers["X-Trace-Id"] = incoming
        path = getattr(request.scope.get("route"), "path", "/unmatched")
        REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
        REQUEST_LATENCY.labels(method=method, path=path).observe(
            time.perf_counter() - start
        )
        trace_id_var.reset(token)
        user_id_var.reset(user_token)
        principal_var.reset(principal_token)
        data_level_var.reset(data_token)
        return response

    app.mount("/metrics", make_asgi_app())
