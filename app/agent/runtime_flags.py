"""G5 · 运行时降级开关中心：不重启进程即可秒级回退主链路。

设计口径（与项目既有"克制"风格一致）：

- **进程内状态是权威**：当前部署是单进程 uvicorn（`evals/load_test.py`、`Dockerfile`
  均为单 worker）。多副本部署时开关需由运维逐副本下发，本模块不假装是分布式配置中心。
- **默认值仍来自环境变量**：`KG_ENABLED` / `RERANK_URL` / `LLM_API_KEY` 等仍是唯一配置口径，
  运行时开关只做"覆盖"，`set_flag(name, None)` 即恢复环境变量默认，避免出现两套互相打架的配置。
- **关闭必须能说清降级行为**：每个开关都自带 `fallback` 说明，被关闭的原因要落进
  检索诊断 / `degradationReasons` / AgentRun 审计，不允许"静默关掉还在报成功"。
- **切换留痕**：每次切换写治理审计（`flag.update`），并暴露 Prometheus 指标 `eaos_runtime_flag`。

开关清单与关闭后的回退路径见 `snapshot()`；消费点见 `app/services/llm.py`、
`app/services/materials.py`、`app/agent/retrieval.py`、`app/agent/ltr.py`、`app/services/policy.py`、
`app/services/factcheck.py`、`app/kg/build.py`。
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Callable

from prometheus_client import Gauge

from ..config import settings
from ..observability import _metric as metric

logger = logging.getLogger(__name__)

FLAG_STATE = metric(
    Gauge, "eaos_runtime_flag", "Runtime degradation flag (1=enabled, 0=disabled)", ["flag"]
)


@dataclass(frozen=True)
class FlagSpec:
    """一个运行时开关：默认值来源 + 关闭后的回退路径。"""

    name: str
    title: str
    config_key: str
    fallback: str
    default: Callable[[], bool]


FLAG_SPECS: tuple[FlagSpec, ...] = (
    FlagSpec(
        "kg", "图谱召回（G1）", "KG_ENABLED",
        "关闭后不走进图路，检索退化为 BM25 + Dense 两路 RRF + 精排",
        lambda: bool(settings.kg_enabled),
    ),
    FlagSpec(
        "semantic_rerank", "语义精排（CrossEncoder / 远端 Rerank）", "RERANK_URL / RERANK_LOCAL_MODEL",
        "关闭后跳过语义精排，退化为确定性词法重排并标记 degraded",
        lambda: bool(settings.rerank_local_model or settings.rerank_url),
    ),
    FlagSpec(
        "remote_llm", "外部对话 / 抽取模型", "LLM_API_KEY",
        "关闭后不调用外部模型，各链路走既有规则化兜底并标记 degraded",
        lambda: bool(settings.llm_api_key),
    ),
    FlagSpec(
        "remote_embedding", "外部向量模型", "EMBEDDING_API_KEY / EMBEDDING_MODEL",
        "关闭后检索跳过 Dense 路（不混用哈希向量顶替），保留 BM25 与图路并标记 degraded",
        lambda: bool(settings.embedding_api_key and settings.embedding_model),
    ),
    FlagSpec(
        "factcheck", "模型事实核查（交叉验证）", "默认开启",
        "关闭后核查退化为规则化实现，结论不得解释为核查通过",
        lambda: True,
    ),
    FlagSpec(
        "model_routing", "模型分层路由（G4）", "LLM_ROUTING_ENABLED",
        "关闭后生成类调用一律走标准层（LLM_MODEL_TIER_STANDARD / LLM_MODEL_GENERATION），"
        "路由决策仍记审计但 tier 恒为 standard",
        lambda: bool(settings.llm_routing_enabled),
    ),
    FlagSpec(
        "ltr", "LTR 学习排序（G9）", "LTR_MODE",
        "关闭后不走进排序模型，检索顺序退回 RRF 保底口径（候选池、顺序与没有 LTR 时完全一致）",
        lambda: (settings.ltr_mode or "off").strip().lower() != "off",
    ),
)

_SPECS: dict[str, FlagSpec] = {spec.name: spec for spec in FLAG_SPECS}
_lock = threading.RLock()
_overrides: dict[str, bool] = {}
_initialized = False


def _publish(name: str) -> bool:
    value = enabled(name)
    FLAG_STATE.labels(flag=name).set(1 if value else 0)
    return value


def _load_startup_overrides() -> None:
    raw = (settings.runtime_flag_overrides or "").strip()
    if not raw:
        return
    try:
        data = json.loads(raw)
    except ValueError:
        logger.error("RUNTIME_FLAG_OVERRIDES 不是合法 JSON，已忽略：%s", raw[:200])
        return
    if not isinstance(data, dict):
        logger.error("RUNTIME_FLAG_OVERRIDES 必须是 JSON 对象，已忽略")
        return
    for name, value in data.items():
        if name not in _SPECS:
            logger.warning("RUNTIME_FLAG_OVERRIDES 含未知开关，已忽略：%s", name)
            continue
        _overrides[name] = bool(value)
        logger.warning("运行时开关启动覆盖：%s=%s", name, bool(value))


def _ensure_initialized() -> None:
    global _initialized
    with _lock:
        if _initialized:
            return
        _initialized = True
        _load_startup_overrides()
        for name in _SPECS:
            FLAG_STATE.labels(flag=name).set(1 if enabled(name) else 0)


def enabled(name: str) -> bool:
    """读取开关当前值：运行时覆盖优先，否则回落到环境变量默认。"""
    _ensure_initialized()
    spec = _SPECS.get(name)
    if spec is None:
        raise KeyError(f"unknown runtime flag: {name}")
    with _lock:
        if name in _overrides:
            return bool(_overrides[name])
    return bool(spec.default())


def is_overridden(name: str) -> bool:
    _ensure_initialized()
    with _lock:
        return name in _overrides


def disabled(name: str) -> bool:
    """是否被运行时开关**显式关闭**。

    "配置里本来就没启用"不算运行时降级：否则离线/未配置环境会被误报成故障注入结果，
    也会让"配置默认值"与"运行时覆盖"两件事纠缠在一起。
    """
    return is_overridden(name) and not enabled(name)


def describe(name: str) -> dict:
    spec = _SPECS[name]
    return {
        "name": name,
        "title": spec.title,
        "enabled": enabled(name),
        "configDefault": bool(spec.default()),
        "source": "runtime-override" if is_overridden(name) else "configuration",
        "configKey": spec.config_key,
        "fallback": spec.fallback,
    }


def set_flag(name: str, value: bool | None, *, operator: str = "", reason: str = "") -> dict:
    """运行时切换开关；`value=None` 表示恢复环境变量默认。

    只改内存状态，审计与提交由调用方（HTTP 管理端点）负责，避免此处持有数据库会话。
    """
    _ensure_initialized()
    spec = _SPECS.get(name)
    if spec is None:
        raise KeyError(f"unknown runtime flag: {name}")
    before = enabled(name)
    with _lock:
        if value is None:
            _overrides.pop(name, None)
        else:
            _overrides[name] = bool(value)
    after = _publish(name)
    logger.warning(
        "运行时开关切换：%s %s -> %s（operator=%s reason=%s）",
        name, before, after, operator or "-", reason or "-",
    )
    state = describe(name)
    state.update({"changed": before != after, "previous": before})
    return state


def snapshot() -> dict:
    _ensure_initialized()
    return {name: describe(name) for name in _SPECS}


def reset(overrides: dict[str, bool] | None = None) -> None:
    """测试与运维复位：清空运行时覆盖，可选注入一组新覆盖。"""
    global _initialized
    with _lock:
        _overrides.clear()
        if overrides:
            _overrides.update({k: bool(v) for k, v in overrides.items() if k in _SPECS})
        _initialized = True
        for name in _SPECS:
            FLAG_STATE.labels(flag=name).set(1 if enabled(name) else 0)