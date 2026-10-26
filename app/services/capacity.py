"""G3 · 耗时链路容量隔离：LLM / Embedding / Rerank 各自独立线程池 + 有界队列。

口径（G3 要求"超限快速失败而不是拖垮全站"）：

- 每个池的并发上限 = `*_POOL_WORKERS`，排队上限 = `*_POOL_QUEUE`；
  闸门计数 = 并发 + 排队，超出即**非阻塞快速失败**（`CapacityError`），永不无限排队。
- 池内任务通过 `copy_context()` 继承审计上下文，`step()` / `current_run` 在池线程内依然生效。
- 快速失败在上层被翻译成既有降级路径，不产生新的业务失败：
  LLM → `LLMCapacityError`（政策问答退化为检索兜底、公告生成降级为规则化草稿）、
  Embedding → `EmbeddingError`（检索跳过 Dense 路，不混用哈希向量）、
  Rerank → 词法降级并标记 `degraded`。
- 例外：公告流式端点已经开始输出 SSE，池满只能走既有错误事件通道，无法中途替换草稿。
- `*_POOL_WORKERS=0` 表示关闭该池（直通执行），仅用于排障，不作为生产默认。
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import copy_context
from dataclasses import dataclass

from prometheus_client import Counter, Gauge

from ..config import settings
from ..observability import _metric as metric

logger = logging.getLogger(__name__)

POOLS: tuple[str, ...] = ("llm", "embedding", "rerank")

CAPACITY_REJECTED = metric(
    Counter, "eaos_capacity_rejected_total",
    "Calls fast-failed because a bounded pool was saturated", ["pool"],
)
CAPACITY_INFLIGHT = metric(
    Gauge, "eaos_capacity_pool_inflight",
    "Calls held by a bounded pool (running + queued)", ["pool"],
)


class CapacityError(RuntimeError):
    """耗时链路容量已满：明确快速失败，交由上层降级，不排队。"""

    def __init__(self, pool: str, reason: str = "queue_full"):
        super().__init__(f"{pool} 容量已满（{reason}），已快速失败")
        self.pool = pool
        self.reason = reason


@dataclass
class _Pool:
    name: str
    workers: int
    queue_limit: int
    executor: ThreadPoolExecutor | None = None
    gate: threading.Semaphore | None = None
    inflight: int = 0
    rejected: int = 0

    @property
    def bounded(self) -> bool:
        return self.gate is not None


_pools: dict[str, _Pool] = {}
_lock = threading.RLock()


def _limits(name: str) -> tuple[int, int]:
    if name == "llm":
        return settings.llm_pool_workers, settings.llm_pool_queue
    if name == "embedding":
        return settings.embedding_pool_workers, settings.embedding_pool_queue
    if name == "rerank":
        return settings.rerank_pool_workers, settings.rerank_pool_queue
    raise KeyError(f"unknown capacity pool: {name}")


def _pool(name: str) -> _Pool:
    with _lock:
        state = _pools.get(name)
        if state is None:
            workers, queue_limit = _limits(name)
            queue_limit = max(0, queue_limit)
            state = _Pool(name=name, workers=max(0, workers), queue_limit=queue_limit)
            if state.workers > 0:
                state.executor = ThreadPoolExecutor(
                    max_workers=state.workers, thread_name_prefix=f"eaos-{name}",
                )
                state.gate = threading.Semaphore(state.workers + state.queue_limit)
            else:
                logger.warning("容量池 %s 已关闭（workers=0），耗时调用将直通执行", name)
            _pools[name] = state
        return state


def _enter(state: _Pool) -> bool:
    gate = state.gate
    if gate is None:
        return True
    if not gate.acquire(blocking=False):
        return False
    with _lock:
        state.inflight += 1
        # 指标必须在锁内发布：锁外写会让并发下的旧值覆盖新值，指标长期停在错误读数。
        CAPACITY_INFLIGHT.labels(pool=state.name).set(state.inflight)
    return True


def _leave(state: _Pool) -> None:
    if state.gate is None:
        return
    with _lock:
        state.inflight = max(0, state.inflight - 1)
        CAPACITY_INFLIGHT.labels(pool=state.name).set(state.inflight)
    state.gate.release()


def _reject(state: _Pool) -> None:
    with _lock:
        state.rejected += 1
    CAPACITY_REJECTED.labels(pool=state.name).inc()


def run(pool: str, fn, *args, **kwargs):
    """在受配额约束的池内执行同步调用；池满立即抛 `CapacityError`。"""
    state = _pool(pool)
    if not state.bounded:
        return fn(*args, **kwargs)
    if not _enter(state):
        _reject(state)
        raise CapacityError(pool)
    try:
        # 池线程必须继承审计上下文，否则 AgentRun 的 model.chat 等步骤会丢失。
        context = copy_context()
        return state.executor.submit(context.run, fn, *args, **kwargs).result()
    finally:
        _leave(state)


@contextmanager
def slot(pool: str):
    """只占配额、不换线程：供流式生成等无法跨线程的调用使用。"""
    state = _pool(pool)
    if not state.bounded:
        yield
        return
    if not _enter(state):
        _reject(state)
        raise CapacityError(pool)
    try:
        yield
    finally:
        _leave(state)


def snapshot() -> dict:
    with _lock:
        return {
            name: {
                "workers": state.workers, "queueLimit": state.queue_limit,
                "inflight": state.inflight, "bounded": state.bounded,
                "rejected": state.rejected,
            }
            for name, state in _pools.items()
        }


def reset() -> None:
    """测试复位：关闭线程池并清空计数，下次调用按当前配置重建。"""
    with _lock:
        for state in _pools.values():
            if state.executor is not None:
                state.executor.shutdown(wait=False)
            CAPACITY_INFLIGHT.labels(pool=state.name).set(0)
        _pools.clear()