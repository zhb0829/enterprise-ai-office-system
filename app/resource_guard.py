"""G3 · 租户资源隔离（AI 服务侧第二道防线）：令牌桶限流 + 并发配额。

- **第一道防线在 Java 网关**（`admin-server` 的 `TenantRateLimitFilter`），本模块是
  AI 服务自己的兜底：网关漏配、内部直连或 worker 被绕过时，单租户打满仍不得挤占其他租户。
- **超限快速失败**：429 + `Retry-After` + `X-RateLimit-*`，不排队、不重试、不拖垮全站。
- **执行位置**：注册在可观测性中间件之前（更内层），因此运行身份已解析完成。
- **未认证请求不进租户配额**：它们会被鉴权层直接拒绝，既不该占用某个租户的额度，
  也不该把 403 掩盖成 429（鉴权失败与限流是两件事）。匿名流量的防刷由 Java 网关第一道防线负责
  （Spring Security 在限流之前就返回 401）。
- **租户键**来自可信身份头解析出的 `Principal.tenant_id`，客户端自报的租户头不参与配额计算。
- 默认不把限流事件写治理审计表：高频拒绝落库会反噬被保护的服务，需要留痕时显式打开
  `RATE_LIMIT_AUDIT_ENABLED`；日志与 Prometheus 指标 `eaos_tenant_throttled_total` 始终记录。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field

from prometheus_client import Counter, Gauge

from .config import settings
from .observability import _metric as metric

logger = logging.getLogger("governance.ratelimit")

THROTTLED = metric(
    Counter, "eaos_tenant_throttled_total",
    "Requests fast-failed by tenant resource isolation", ["tenant", "reason"],
)
TENANT_INFLIGHT = metric(
    Gauge, "eaos_tenant_inflight", "In-flight requests per tenant", ["tenant"],
)


@dataclass(frozen=True)
class Quota:
    rps: float
    burst: int
    concurrency: int

    @property
    def concurrency_limited(self) -> bool:
        return self.concurrency > 0


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    retry_after: float = 0.0
    limit: float = 0.0
    remaining: float = 0.0
    reset_after: float = 0.0
    concurrency_limit: int = 0
    concurrency_inflight: int = 0

    def headers(self) -> dict:
        headers = {
            "X-RateLimit-Limit": str(int(self.limit)),
            "X-RateLimit-Remaining": str(max(0, int(self.remaining))),
            "X-RateLimit-Reset": str(max(0, int(self.reset_after + 0.999))),
            "X-Tenant-Concurrency-Limit": str(self.concurrency_limit),
            "X-Tenant-Concurrency-Inflight": str(self.concurrency_inflight),
        }
        if not self.allowed:
            headers["Retry-After"] = str(max(1, int(self.retry_after + 0.999)))
        return headers


class _Bucket:
    """标准令牌桶：容量 burst，补充速率 rps。"""

    __slots__ = ("rps", "burst", "tokens", "updated")

    def __init__(self, quota: Quota, now: float):
        self.rps = max(1e-6, float(quota.rps))
        self.burst = max(1, int(quota.burst))
        self.tokens = float(self.burst)
        self.updated = now

    def take(self, now: float) -> tuple[bool, float]:
        elapsed = max(0.0, now - self.updated)
        self.updated = now
        self.tokens = min(float(self.burst), self.tokens + elapsed * self.rps)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True, 0.0
        return False, (1.0 - self.tokens) / self.rps

    def replenish_after(self) -> float:
        return (float(self.burst) - self.tokens) / self.rps


class Limiter:
    """进程内租户限流器：每租户一个令牌桶 + 并发计数（含全局上限）。"""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.RLock()
        self._buckets: dict[str, _Bucket] = {}
        self._quota: dict[str, Quota] = {}
        self._inflight: dict[str, int] = {}
        self._total = 0

    def acquire(self, tenant: str, quota: Quota, global_concurrency: int) -> Decision:
        now = self._clock()
        with self._lock:
            inflight = self._inflight.get(tenant, 0)
            if global_concurrency > 0 and self._total >= global_concurrency:
                return Decision(
                    allowed=False, reason="global_concurrency", retry_after=0.05,
                    limit=quota.rps, remaining=0.0, reset_after=0.05,
                    concurrency_limit=quota.concurrency, concurrency_inflight=inflight,
                )
            if quota.concurrency_limited and inflight >= quota.concurrency:
                return Decision(
                    allowed=False, reason="tenant_concurrency", retry_after=0.05,
                    limit=quota.rps, remaining=0.0, reset_after=0.05,
                    concurrency_limit=quota.concurrency, concurrency_inflight=inflight,
                )
            bucket = self._buckets.get(tenant)
            if bucket is None or (bucket.rps, bucket.burst) != (max(1e-6, float(quota.rps)), max(1, int(quota.burst))):
                bucket = _Bucket(quota, now)
                self._buckets[tenant] = bucket
            ok, wait = bucket.take(now)
            if not ok:
                return Decision(
                    allowed=False, reason="tenant_rate", retry_after=wait,
                    limit=quota.rps, remaining=bucket.tokens, reset_after=wait,
                    concurrency_limit=quota.concurrency, concurrency_inflight=inflight,
                )
            self._inflight[tenant] = inflight + 1
            self._total += 1
            self._quota[tenant] = quota
            TENANT_INFLIGHT.labels(tenant=tenant).set(inflight + 1)
            return Decision(
                allowed=True, limit=quota.rps, remaining=bucket.tokens,
                reset_after=bucket.replenish_after(),
                concurrency_limit=quota.concurrency, concurrency_inflight=inflight + 1,
            )

    def release(self, tenant: str) -> None:
        with self._lock:
            current = self._inflight.get(tenant, 0)
            if current <= 0:
                return
            self._inflight[tenant] = current - 1
            self._total = max(0, self._total - 1)
            TENANT_INFLIGHT.labels(tenant=tenant).set(current - 1)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "totalInflight": self._total,
                "tenants": {
                    tenant: {
                        "inflight": count,
                        "quota": {
                            "rps": self._quota[tenant].rps,
                            "burst": self._quota[tenant].burst,
                            "concurrency": self._quota[tenant].concurrency,
                        } if tenant in self._quota else None,
                    }
                    for tenant, count in self._inflight.items()
                },
            }


def default_quota() -> Quota:
    return Quota(
        rps=float(settings.rate_limit_rps),
        burst=int(settings.rate_limit_burst),
        concurrency=int(settings.rate_limit_max_concurrency),
    )


@dataclass
class QuotaConfig:
    """按 `RATE_LIMIT_TENANT_OVERRIDES` 解析后的租户配额表（含配置指纹，便于热更新）。"""

    defaults: Quota
    overrides: dict[str, dict] = field(default_factory=dict)
    fingerprint: str = ""

    def quota_for(self, tenant: str) -> Quota:
        item = self.overrides.get(tenant) or {}
        return Quota(
            rps=float(item.get("rps", self.defaults.rps)),
            burst=int(item.get("burst", self.defaults.burst)),
            concurrency=int(item.get("concurrency", self.defaults.concurrency)),
        )

    @property
    def global_concurrency(self) -> int:
        return int(settings.rate_limit_global_concurrency)


def load_quota_config() -> QuotaConfig:
    raw = (settings.rate_limit_tenant_overrides or "").strip()
    defaults = default_quota()
    fingerprint = f"{defaults.rps}|{defaults.burst}|{defaults.concurrency}|{raw}"
    overrides: dict[str, dict] = {}
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                overrides = {str(k): v for k, v in data.items() if isinstance(v, dict)}
            else:
                logger.error("RATE_LIMIT_TENANT_OVERRIDES 必须是 JSON 对象，已忽略")
        except ValueError:
            logger.error("RATE_LIMIT_TENANT_OVERRIDES 不是合法 JSON，已忽略：%s", raw[:200])
    return QuotaConfig(defaults=defaults, overrides=overrides, fingerprint=fingerprint)


def _exempt(path: str, raw_paths: str) -> bool:
    for item in (raw_paths or "").split(","):
        prefix = item.strip()
        if prefix and path.startswith(prefix):
            return True
    return False


def install_resource_guard(app, *, limiter: Limiter | None = None) -> Limiter:
    """挂载租户限流中间件；必须在 `install_observability` 之前调用（见 app/main.py）。"""
    guard = limiter or Limiter()
    app.state.resource_guard = guard
    cached = {"fingerprint": None, "config": None}

    def quota_config() -> QuotaConfig:
        config = load_quota_config()
        if cached["fingerprint"] != config.fingerprint:
            cached["fingerprint"] = config.fingerprint
            cached["config"] = config
        return cached["config"]

    @app.middleware("http")
    async def tenant_resource_guard(request, call_next):
        from fastapi.responses import JSONResponse
        from .agent.governance import principal_var

        if not settings.rate_limit_enabled:
            return await call_next(request)
        path = request.url.path
        if _exempt(path, settings.rate_limit_exempt_paths):
            return await call_next(request)
        principal = principal_var.get()
        if not principal.authenticated:
            # 未认证请求不进租户配额：让鉴权层给出 403/401，而不是被 429 掩盖。
            return await call_next(request)
        # authenticated 保证 tenant_id 非空，因此不存在"匿名共享桶"。
        tenant = principal.tenant_id
        config = quota_config()
        decision = guard.acquire(tenant, config.quota_for(tenant), config.global_concurrency)
        if not decision.allowed:
            THROTTLED.labels(tenant=tenant, reason=decision.reason).inc()
            logger.warning(
                "租户配额拒绝 tenant=%s path=%s reason=%s inflight=%s",
                tenant, path, decision.reason, decision.concurrency_inflight,
            )
            if settings.rate_limit_audit_enabled:
                await _persist_rejection(tenant, path, decision)
            return JSONResponse(
                {
                    "detail": {
                        "message": "租户配额已用尽，请稍后重试",
                        "reason": decision.reason,
                        "tenant": tenant,
                    }
                },
                status_code=429,
                headers=decision.headers(),
            )
        try:
            response = await call_next(request)
        finally:
            guard.release(tenant)
        for name, value in decision.headers().items():
            response.headers.setdefault(name, value)
        return response

    return guard


async def _persist_rejection(tenant: str, path: str, decision: Decision) -> None:
    """可选留痕：只在显式打开 RATE_LIMIT_AUDIT_ENABLED 时写治理审计。"""
    from starlette.concurrency import run_in_threadpool
    from . import db as app_db
    from .agent.governance import audit, principal_var

    principal = principal_var.get()

    def persist() -> None:
        try:
            with app_db.SessionLocal() as db:
                audit(db, "ratelimit.reject", path, outcome="denied",
                      details={"reason": decision.reason, "tenant": tenant}, principal=principal)
                db.commit()
        except Exception:  # noqa: BLE001  留痕失败不得把 429 变成 500
            logger.exception("限流审计落库失败 tenant=%s", tenant)

    await run_in_threadpool(persist)