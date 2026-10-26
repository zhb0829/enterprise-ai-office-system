"""G6 · 成本核算口径：按租户 / 功能 / 模型核算 token 成本。

三条纪律（沿用本项目"不伪造"口径）：

1. **单价只来自配置**：价格表 `LLM_PRICE_TABLE` 是唯一价格来源，代码里不内置任何单价——
   内置单价会随供应商调价静默过期，比没有单价更危险。
2. **未知即 null**：模型未收录、或供应商没返回 usage，成本一律 `null`，不用 0 顶替、不估算。
3. **部分已知必须自曝缺口**：`cost` 只累加已定价部分，同时给出 `cost_complete` /
   `unpriced_models`；调用方不得把 `cost` 当作完整账单。

单位口径：**元 / 百万 token，仅 CNY**。其他币种或单位的条目在解析时被拒绝并记录原因——
把不同币种相加会得出一个"看似精确但错误"的总额。

明细随 AgentRun 一次性落库（`agent_run.usage`），这里不单独建每次调用的流水表：
把每次模型调用落一行会把写放大压到被保护的业务库上（与 G3"高频拒绝默认不落库"同一条纪律）。
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime

from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agent.models import AgentRun
from ..agent.runtime import current_run
from ..config import settings
from ..observability import _metric as metric

logger = logging.getLogger(__name__)

CURRENCY = "CNY"
UNIT = "per_million_tokens"
# 历史 run 只有总量、没有模型分桶：如实记"未归属"，不猜模型
UNATTRIBUTED = "(unattributed)"
UNKNOWN_MODEL = "(unknown-model)"

REASON_MODEL_NOT_PRICED = "model-not-priced"
REASON_TOKEN_USAGE_MISSING = "token-usage-missing"
REASON_USAGE_NOT_ATTRIBUTED = "usage-not-attributed"

MODEL_TOKENS = metric(
    Counter, "eaos_model_tokens_total",
    "Tokens reported by model providers (input/output)", ["model", "purpose", "kind"],
)
MODEL_COST = metric(
    Counter, "eaos_model_cost_cny_total",
    "Cost accrued for priced models only (CNY, yuan per million tokens)", ["model", "purpose"],
)
MODEL_UNPRICED = metric(
    Counter, "eaos_model_unpriced_calls_total",
    "Model calls whose cost is unknown (not estimated)", ["model", "reason"],
)


def _model_key(model: str) -> str:
    return str(model or "").strip().lower()


@dataclass(frozen=True)
class Price:
    """一个模型的价格：元 / 百万 token。"""

    model: str
    input_per_million: float
    output_per_million: float

    def cost(self, input_tokens: int | None, output_tokens: int | None) -> float | None:
        """算成本；任一 token 数未知即返回 None（不把未知当 0）。"""
        if input_tokens is None or output_tokens is None:
            return None
        return round(
            input_tokens / 1_000_000 * self.input_per_million
            + output_tokens / 1_000_000 * self.output_per_million,
            9,
        )


@dataclass
class PriceTable:
    prices: dict[str, Price] = field(default_factory=dict)
    rejected: list[dict] = field(default_factory=list)
    error: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.prices)

    def price_for(self, model: str) -> Price | None:
        return self.prices.get(_model_key(model))

    def as_dict(self) -> dict:
        return {
            "currency": CURRENCY, "unit": UNIT,
            "pricedModels": sorted(price.model for price in self.prices.values()),
            "rejectedEntries": self.rejected,
            "error": self.error,
        }


def _reject_reason(spec) -> str:
    """条目不合规的原因；返回空串表示接受。宁可拒绝条目，也不猜价格。"""
    if not isinstance(spec, dict):
        return "entry-not-object"
    currency = str(spec.get("currency", CURRENCY)).strip().upper()
    if currency != CURRENCY:
        return f"currency-not-supported:{currency}"
    unit = str(spec.get("unit", UNIT)).strip()
    if unit != UNIT:
        return f"unit-not-supported:{unit}"
    for key in ("input", "output"):
        if key not in spec:
            # 缺 output 不等于"输出免费"：要求显式写 0
            return f"missing-{key}-price"
        value = spec[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return f"invalid-{key}-price"
    return ""


def parse_price_table(raw: str) -> PriceTable:
    table = PriceTable()
    text = (raw or "").strip()
    if not text:
        return table
    try:
        data = json.loads(text)
    except ValueError:
        table.error = "LLM_PRICE_TABLE 不是合法 JSON，已按空价格表处理（成本记 null）"
        logger.error(table.error)
        return table
    if not isinstance(data, dict):
        table.error = "LLM_PRICE_TABLE 必须是 JSON 对象：{model: {input, output}}"
        logger.error(table.error)
        return table
    for name, spec in data.items():
        model = str(name).strip()
        reason = _reject_reason(spec) or ("" if model else "empty-model-name")
        if reason:
            table.rejected.append({"model": model, "reason": reason})
            logger.warning("价格表条目被拒绝：model=%s reason=%s", model or "(empty)", reason)
            continue
        table.prices[_model_key(model)] = Price(
            model=model,
            input_per_million=float(spec["input"]),
            output_per_million=float(spec["output"]),
        )
    if table.rejected:
        logger.error(
            "价格表有 %d 条被拒绝，这些模型的成本将记 null：%s",
            len(table.rejected), table.rejected,
        )
    return table


_lock = threading.RLock()
_table: PriceTable | None = None


def price_table() -> PriceTable:
    """惰性解析价格表（进程内缓存）；配置改动用 `reload_price_table()` 生效。"""
    global _table
    with _lock:
        if _table is None:
            _table = parse_price_table(settings.llm_price_table)
        return _table


def reload_price_table() -> PriceTable:
    global _table
    with _lock:
        _table = None
    return price_table()


def reset() -> None:
    """测试复位：清空缓存，下次按当前配置重建。"""
    reload_price_table()


def _publish(entry: dict) -> None:
    model = entry["model"] or UNKNOWN_MODEL
    purpose = entry["purpose"] or "unspecified"
    if entry["tokensAvailable"]:
        if entry["inputTokens"] is not None:
            MODEL_TOKENS.labels(model=model, purpose=purpose, kind="input").inc(entry["inputTokens"])
        if entry["outputTokens"] is not None:
            MODEL_TOKENS.labels(model=model, purpose=purpose, kind="output").inc(entry["outputTokens"])
    if entry["priced"] and entry["cost"]:
        MODEL_COST.labels(model=model, purpose=purpose).inc(entry["cost"])
    if entry["unpricedReason"]:
        MODEL_UNPRICED.labels(model=model, reason=entry["unpricedReason"]).inc(int(entry["calls"] or 1))


def _add_node(node: dict, entry: dict) -> None:
    """把一次调用累加进一个用量节点（顶层模型的桶或其下的功能桶）。

    token 未知是**不可逆**的：某一侧只要出现过"拿不到"，该侧此后一律记 `null`，
    后续已知数字不得把它"复原"成看起来完整的合计（否则报表会把已知部分当全部）。
    """
    node["calls"] = int(node.get("calls", 0)) + int(entry["calls"] or 1)
    if entry["tokensAvailable"]:
        for key, value in (("input_tokens", entry["inputTokens"]), ("output_tokens", entry["outputTokens"])):
            if value is None:
                node[key] = None
            elif node.get(key) is not None:
                node[key] = node[key] + value
    else:
        node["input_tokens"] = None
        node["output_tokens"] = None
    if not entry.get("tokensComplete", entry["tokensAvailable"]):
        node["tokens_complete"] = False
    if entry["priced"]:
        node["cost"] = round((node.get("cost") or 0.0) + entry["cost"], 9)
    else:
        node["cost_complete"] = False
        reason = entry["unpricedReason"] or "unknown"
        reasons = node.setdefault("unpriced_reasons", [])
        if reason not in reasons:
            reasons.append(reason)


def _new_node() -> dict:
    return {
        "input_tokens": 0, "output_tokens": 0, "calls": 0,
        "cost": None, "cost_complete": True, "tokens_complete": True,
        "unpriced_reasons": [], "purposes": {},
    }


def accumulate(usage: dict, entry: dict) -> dict:
    """把一次模型用量累加进 usage（供 `llm.py` 与 embedding/rerank 调用点共用）。

    结构（`by_model` 是唯一权威明细，顶层字段是它的汇总视图，兼容历史消费方）：

    ```
    usage = {
      "input_tokens": 10, "output_tokens": 8,
      "cost": 0.000084, "cost_complete": True, "currency": "CNY",
      "usage_complete": True, "tokens_complete": True, "unpriced_models": [],
      "by_model": {"model-a": {"input_tokens": 10, "output_tokens": 8, "calls": 1,
                               "cost": 0.000084, "cost_complete": True,
                               "tokens_complete": True,
                               "purposes": {"policy.answer": {...同结构...}}}},
    }
    ```

    `usage_complete` 表示"每次调用都拿回了 usage"，`tokens_complete` 表示"每次调用的
    输入与输出 token 都有值"——后者更严：只回了 `total_tokens` 时前者可能为真、后者为假。
    """
    model = entry["model"] or UNKNOWN_MODEL
    purpose = entry["purpose"] or "unspecified"
    buckets = usage.setdefault("by_model", {})
    bucket = buckets.get(model)
    if bucket is None:
        bucket = _new_node()
        buckets[model] = bucket
    _add_node(bucket, entry)
    purpose_node = bucket["purposes"].get(purpose)
    if purpose_node is None:
        purpose_node = {key: value for key, value in _new_node().items() if key != "purposes"}
        bucket["purposes"][purpose] = purpose_node
    _add_node(purpose_node, entry)

    if entry["tokensAvailable"]:
        for key, value in (("input_tokens", entry["inputTokens"]), ("output_tokens", entry["outputTokens"])):
            if value is None:
                usage[key] = None
            elif usage.get(key) is not None:
                usage[key] = (usage.get(key) or 0) + value
    else:
        usage["usage_complete"] = False
        usage["input_tokens"] = None
        usage["output_tokens"] = None

    priced = [node["cost"] for node in buckets.values() if node.get("cost") is not None]
    usage["cost"] = round(sum(priced), 9) if priced else None
    usage["cost_complete"] = all(node.get("cost_complete", True) for node in buckets.values())
    usage["tokens_complete"] = all(node.get("tokens_complete", True) for node in buckets.values())
    usage["unpriced_models"] = sorted(
        name for name, node in buckets.items() if not node.get("cost_complete", True)
    )
    usage["currency"] = CURRENCY
    usage["price_unit"] = UNIT
    return usage


def record_usage(
    *, model: str, purpose: str = "", input_tokens: int | None = None,
    output_tokens: int | None = None, calls: int = 1,
    tokens_available: bool | None = None,
) -> dict:
    """登记一次模型用量：发布指标、累加进当前 AgentRun，并返回本次账目条目。

    `tokens_available=False` 用于供应商不返回 usage 的调用（例如按文档计费的 rerank）：
    此时只记调用次数，成本记 null 并把原因标成 `token-usage-missing`。

    **只在输入与输出 token 都有值时计价**：供应商只回 `total_tokens`（或某一侧缺失）时，
    按缺失侧 = 0 计价会静默低报，那属于伪造成本。
    """
    if tokens_available is None:
        tokens_available = input_tokens is not None or output_tokens is not None
    tokens_complete = bool(
        tokens_available and input_tokens is not None and output_tokens is not None
    )
    price = price_table().price_for(model)
    entry = {
        "model": model or UNKNOWN_MODEL, "purpose": purpose or "",
        "calls": int(calls or 1), "tokensAvailable": bool(tokens_available),
        "tokensComplete": tokens_complete,
        "inputTokens": input_tokens, "outputTokens": output_tokens,
        "cost": None, "priced": False, "unpricedReason": "",
    }
    if not tokens_complete:
        entry["unpricedReason"] = REASON_TOKEN_USAGE_MISSING
    elif price is None:
        entry["unpricedReason"] = REASON_MODEL_NOT_PRICED
    else:
        entry["cost"] = price.cost(input_tokens, output_tokens)
        entry["priced"] = entry["cost"] is not None
        if not entry["priced"]:
            entry["unpricedReason"] = REASON_TOKEN_USAGE_MISSING

    _publish(entry)
    capture = current_run.get()
    if capture is not None:
        with capture.lock:
            accumulate(capture.usage, entry)
    return entry


# ===== 按租户 / 功能 / 模型聚合（G6 交付口径） =====

GROUP_DIMENSIONS = ("model", "purpose", "intent", "tenant")


def collect_runs(
    db: Session, *, tenant_id: str = "", since: datetime | None = None,
    until: datetime | None = None, intent: str = "", max_runs: int | None = None,
) -> tuple[list[dict], bool]:
    """按窗口读 AgentRun 的成本相关字段；返回 (记录, 是否被行数上限截断)。

    只取聚合需要的列，不整行取出 steps / 快照，避免运维查询把大字段拖进内存。
    """
    limit = int(max_runs or settings.cost_query_max_runs)
    statement = select(
        AgentRun.run_id, AgentRun.tenant_id, AgentRun.intent, AgentRun.usage, AgentRun.started_at,
    )
    if tenant_id:
        statement = statement.where(AgentRun.tenant_id == tenant_id)
    if since is not None:
        statement = statement.where(AgentRun.started_at >= since)
    if until is not None:
        statement = statement.where(AgentRun.started_at <= until)
    if intent:
        statement = statement.where(AgentRun.intent == intent)
    statement = statement.order_by(AgentRun.started_at.desc()).limit(limit + 1)
    rows = db.execute(statement).all()
    truncated = len(rows) > limit
    records = [
        {
            "runId": row[0], "tenantId": row[1] or "default", "intent": row[2] or "",
            "usage": row[3] or {}, "startedAt": row[4].isoformat() if row[4] else None,
        }
        for row in rows[:limit]
    ]
    return records, truncated


def _dim_values(
    dims: tuple[str, ...], *, model=None, purpose=None, intent=None, tenant=None,
) -> dict:
    """分组维度值。

    - `intent`：业务功能（AgentRun.intent，如 policy_qa / policy_interpretation）
    - `purpose`：模型调用用途（usage 明细里的 key，如 policy.answer / factcheck）
    两者不是同一层概念，成本报表需要分别给出，混成一个会让"按功能核算"变得不可解释。
    """
    return {
        "model": model if "model" in dims else None,
        "purpose": purpose if "purpose" in dims else None,
        "intent": intent if "intent" in dims else None,
        "tenant": tenant if "tenant" in dims else None,
    }


def aggregate(records: list[dict], *, group_by: tuple[str, ...] = ("model",)) -> dict:
    """把 `collect_runs` 的记录按维度聚合成成本报表。

    汇总口径：`cost` **只含已定价模型**；只要存在未知成本，`costComplete=false` 且
    `unpricedModels` / `unpricedReasons` 会列出缺口。不要把 `cost` 当完整账单。
    """
    dims = tuple(dim for dim in group_by if dim in GROUP_DIMENSIONS) or ("model",)
    groups: dict[tuple, dict] = {}
    total = {
        "inputTokens": 0, "outputTokens": 0, "calls": 0, "runs": 0,
        "cost": None, "costComplete": True, "tokensComplete": True,
        "unpricedModels": [], "unpricedReasons": [],
    }
    seen_runs: set[str] = set()
    unattributed = 0
    zero_usage = 0

    def add(dim_values: dict, node_values: dict, run_id: str) -> None:
        key = tuple(dim_values[dim] for dim in dims)
        node = groups.get(key)
        if node is None:
            node = {
                **dim_values, "inputTokens": 0, "outputTokens": 0, "calls": 0, "runs": 0,
                "cost": None, "costComplete": True, "tokensComplete": True,
                "unpricedModels": [], "unpricedReasons": [], "_runs": set(),
            }
            groups[key] = node
        for key, source in (("inputTokens", "input_tokens"), ("outputTokens", "output_tokens")):
            value = node_values.get(source)
            if value is None:
                # token 未知不可逆：该维度此后只报"已知部分"，不得当成完整合计
                node[key] = None
            elif node[key] is not None:
                node[key] = node[key] + value
        node["calls"] += int(node_values.get("calls") or 0)
        if not node_values.get("tokens_complete", True):
            node["tokensComplete"] = False
        if node_values.get("cost") is not None:
            node["cost"] = round((node["cost"] or 0.0) + node_values["cost"], 9)
        if not node_values.get("cost_complete", True):
            node["costComplete"] = False
            model = dim_values.get("model")
            if model and model not in node["unpricedModels"]:
                node["unpricedModels"].append(model)
            for reason in node_values.get("unpriced_reasons") or []:
                if reason not in node["unpricedReasons"]:
                    node["unpricedReasons"].append(reason)
        if run_id:
            node["_runs"].add(run_id)

    def add_total(node_values: dict, model: str | None, run_id: str) -> None:
        if node_values.get("cost") is not None:
            total["cost"] = round((total["cost"] or 0.0) + node_values["cost"], 9)
        if not node_values.get("cost_complete", True):
            total["costComplete"] = False
            name = model or UNKNOWN_MODEL
            if name not in total["unpricedModels"]:
                total["unpricedModels"].append(name)
            for reason in node_values.get("unpriced_reasons") or []:
                if reason not in total["unpricedReasons"]:
                    total["unpricedReasons"].append(reason)
        for key, source in (("inputTokens", "input_tokens"), ("outputTokens", "output_tokens")):
            value = node_values.get(source)
            if value is None:
                total[key] = None
            elif total[key] is not None:
                total[key] = total[key] + value
        if not node_values.get("tokens_complete", True):
            total["tokensComplete"] = False
        total["calls"] += int(node_values.get("calls") or 0)
        if run_id:
            seen_runs.add(run_id)

    for record in records:
        usage = record.get("usage") or {}
        run_id = str(record.get("runId") or "")
        tenant = record.get("tenantId") or "default"
        intent = record.get("intent") or ""
        by_model = usage.get("by_model")
        if not by_model:
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if not input_tokens and not output_tokens:
                # 零用量运行（离线 / 规则化链路、纯检索）：既没有成本，也不构成"未知成本"缺口。
                # 把它算成缺口会让 costComplete 永远是 false，指标随即失去意义。
                zero_usage += 1
                continue
            # 历史行只有总量：如实记成"未归属"，不猜模型名
            unattributed += 1
            values = {
                "input_tokens": input_tokens, "output_tokens": output_tokens,
                "calls": 1, "cost": None, "cost_complete": False,
                "tokens_complete": input_tokens is not None and output_tokens is not None,
                "unpriced_reasons": [REASON_USAGE_NOT_ATTRIBUTED],
            }
            add(
                _dim_values(
                    dims, model=UNATTRIBUTED, purpose=UNATTRIBUTED, intent=intent, tenant=tenant,
                ),
                values, run_id,
            )
            add_total(values, UNATTRIBUTED, run_id)
            continue
        for model, bucket in by_model.items():
            for node_purpose, node in (bucket.get("purposes") or {}).items():
                add(
                    _dim_values(
                        dims, model=model, purpose=node_purpose, intent=intent, tenant=tenant,
                    ),
                    node, run_id,
                )
                add_total(node, model, run_id)

    rendered = []
    for node in groups.values():
        node = dict(node)
        node["runs"] = len(node.pop("_runs"))
        node["unpricedModels"] = sorted(node["unpricedModels"])
        node["unpricedReasons"] = sorted(node["unpricedReasons"])
        rendered.append(node)
    rendered.sort(
        key=lambda item: (item["cost"] is None, -(item["cost"] or 0), str(sorted(item.items()))),
    )
    total["runs"] = len(seen_runs)
    total["unpricedModels"] = sorted(total["unpricedModels"])
    total["unpricedReasons"] = sorted(total["unpricedReasons"])
    return {
        "currency": CURRENCY,
        "unit": UNIT,
        "groupBy": list(dims),
        "costKnownOnly": True,
        "costComplete": total["costComplete"],
        "tokensComplete": total["tokensComplete"],
        "total": total,
        "unpricedModels": total["unpricedModels"],
        "unpricedReasons": total["unpricedReasons"],
        "unattributedRuns": unattributed,
        "zeroUsageRuns": zero_usage,
        "groups": rendered,
        "pricing": price_table().as_dict(),
        "note": (
            "cost 只累加已定价模型的用量（元/百万token，仅 CNY）；"
            "costComplete=false 表示存在未知成本（模型未定价或供应商未返回 usage），"
            "不得把 cost 当作完整账单，也不要把未知部分按 0 处理。"
            "零用量运行（离线/规则化链路）不计入缺口，单独记在 zeroUsageRuns。"
        ),
    }