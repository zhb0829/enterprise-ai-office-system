"""G4 · 模型分层路由：按用途与问题复杂度选层，并把决策落进 AgentRun 审计。

口径（四条，缺任一条即"不路由"，且必须说清为什么）：

1. **用途可分层**：只有"任务复杂度随用户输入变化"的生成类用途参与分层，
   当前清单是 `ROUTABLE_PURPOSES`（政策问答 / 条款解读 / 起草 / 多轮修改）。
   其他用途——情报摘要、舆情报告与应对建议、润色、会议成稿、资质初稿——任务形态固定，
   按用途记账但恒走标准层（`source=purpose-not-routable`），不会假装被路由过。
   抽取、事实核查、Embedding、Rerank 有专用模型配置，属于"用对模型"而非"按复杂度选模型"，
   即使没显式传 model 也不会被分层覆盖（`source=designated-purpose`）。
2. **复杂度可判定**：打分只用一个整数分值 + 可读信号列表，阈值来自配置
   （`LLM_ROUTING_LIGHT_MAX_SCORE` / `LLM_ROUTING_REASONING_MIN_SCORE`）。
   打分规则是启发式而不是学习模型：可解释、可回归，不需要训练数据（G9 才谈 LTR）。
3. **目标层模型已配置**：轻量层 / 旗舰层未配置时回落标准层，并把原因如实写进决策 ——
   不允许"以为路由了，其实一直走同一个模型"。
4. **路由开关打开**：`LLM_ROUTING_ENABLED` 只是默认值，运行时开关 `model_routing`（G5 开关中心）
   可以热切换；默认关闭，与 G1 图谱同口径——先跑 `evals.routing_compare` 拿到证据再开。

路由决策有两条留痕：`step("model.route")` 落进 `agent_run.steps`（逐步可追溯），
汇总落进 `agent_run.routing`（一次运行的层分布与模型分布，便于按 run 回溯）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from ..agent import runtime_flags
from ..agent.runtime import current_run, step
from ..config import settings

logger = logging.getLogger(__name__)

TIER_LIGHT = "light"
TIER_STANDARD = "standard"
TIER_REASONING = "reasoning"
TIERS = (TIER_LIGHT, TIER_STANDARD, TIER_REASONING)

COMPLEXITY_SIMPLE = "simple"
COMPLEXITY_MODERATE = "moderate"
COMPLEXITY_COMPLEX = "complex"

# 参与分层的用途（生成类，且"任务复杂度随用户输入变化"）
ROUTABLE_PURPOSES = (
    "policy.answer",
    "policy.interpret",
    "draft.generate",
    "draft.revise",
)
# 专用模型用途：不按复杂度选层，只用配置指定的专用模型（此处仅用于审计说明）
DESIGNATED_PURPOSES = {
    "extraction": "LLM_MODEL_EXTRACTION",
    "factcheck": "LLM_MODEL_FACTCHECK",
    "kg.extract": "KG_MODEL 或 LLM_MODEL_EXTRACTION",
    "kg.community": "KG_MODEL 或 LLM_MODEL_EXTRACTION",
    "embedding": "EMBEDDING_MODEL",
    "rerank.policy": "RERANK_MODEL / RERANK_LOCAL_MODEL",
    "meeting.report": "MEETING_REPORT_MODEL",
    "meeting.card": "MEETING_CARD_MODEL",
    "meeting.vision": "MEETING_VISION_MODEL",
}

REASONING_MARKERS = (
    "对比", "区别", "差异", "相比", "为什么", "原因", "影响", "后果", "如何计算",
    "能否同时", "是否冲突", "冲突", "优先级", "如果", "假设", "分别", "结合",
    "综合分析", "测算", "评估", "折算", "叠加",
)
MULTI_HOP_MARKERS = ("依据", "上位", "引用", "关联", "配套", "援引", "参照")
SIMPLE_MARKERS = ("是什么", "有哪些", "哪些", "谁", "何时", "什么时候", "多少", "几天", "工作日", "标准", "材料")
PURPOSE_BOOST = {"draft.generate": 1}

MAX_DECISIONS = 50


@dataclass(frozen=True)
class Decision:
    """一次路由决策：层、模型、分值、信号、为什么。"""

    purpose: str
    tier: str
    model: str
    source: str
    reason: str
    score: int
    complexity: str
    signals: tuple[str, ...] = ()
    routed: bool = False
    changed: bool = False

    def as_dict(self) -> dict:
        return {
            "purpose": self.purpose,
            "tier": self.tier,
            "model": self.model,
            "routed": self.routed,
            "changed": self.changed,
            "score": self.score,
            "complexity": self.complexity,
            "source": self.source,
            "reason": self.reason,
            "signals": list(self.signals),
        }


def standard_model() -> str:
    return settings.llm_model_tier_standard or settings.llm_model_generation


def _distinct_markers(markers: tuple[str, ...], text: str) -> list[str]:
    """命中词去重：`是否冲突` 命中时不再重复计一次 `冲突`，否则同一现象被计两次。"""
    hits = [marker for marker in markers if marker in text]
    return [hit for hit in hits if not any(hit != other and hit in other for other in hits)]


def score_complexity(
    text: str, *, purpose: str = "", citation_count: int = 0, context_chars: int = 0,
) -> tuple[int, list[str]]:
    """启发式复杂度打分：返回 (分值, 可读信号列表)。

    信号只描述"看到了什么"，不描述"答案有多难"——分值可回归、可解释、可复算。
    """
    question = text or ""
    signals: list[str] = []
    score = 0

    length = len(question)
    if length >= 120:
        score += 2
        signals.append(f"length>=120(+2,{length})")
    elif length >= 40:
        score += 1
        signals.append(f"length>=40(+1,{length})")

    questions = question.count("？") + question.count("?")
    if questions >= 2:
        score += 1
        signals.append(f"multi-question(+1,{questions})")

    reasoning = _distinct_markers(REASONING_MARKERS, question)
    if reasoning:
        weight = min(2, len(reasoning))
        score += weight
        signals.append(f"reasoning-markers(+{weight},{','.join(reasoning)})")

    multi_hop = _distinct_markers(MULTI_HOP_MARKERS, question)
    if multi_hop:
        score += 1
        signals.append(f"multi-hop-markers(+1,{','.join(multi_hop)})")

    if citation_count >= 10:
        score += 2
        signals.append(f"citations>=10(+2,{citation_count})")
    elif citation_count >= 6:
        score += 1
        signals.append(f"citations>=6(+1,{citation_count})")

    if context_chars >= 8000:
        score += 2
        signals.append(f"context>=8000(+2,{context_chars})")
    elif context_chars >= 3000:
        score += 1
        signals.append(f"context>=3000(+1,{context_chars})")

    boost = PURPOSE_BOOST.get(purpose, 0)
    if boost:
        score += boost
        signals.append(f"purpose-boost(+{boost},{purpose})")

    simple = next((marker for marker in SIMPLE_MARKERS if marker in question), "")
    if simple and length < 40 and not reasoning:
        score -= 1
        signals.append(f"short-lookup(-1,{simple})")
    if not signals:
        # 没有任何信号本身也是结论：判定为简单问题靠的是"无加分项"，必须写清楚
        signals.append(f"no-complexity-signal(0,{length})")
    return score, signals


def complexity_for(score: int) -> str:
    if score <= settings.llm_routing_light_max_score:
        return COMPLEXITY_SIMPLE
    if score >= settings.llm_routing_reasoning_min_score:
        return COMPLEXITY_COMPLEX
    return COMPLEXITY_MODERATE


def tier_for_score(score: int) -> str:
    complexity = complexity_for(score)
    if complexity == COMPLEXITY_SIMPLE:
        return TIER_LIGHT
    if complexity == COMPLEXITY_COMPLEX:
        return TIER_REASONING
    return TIER_STANDARD


def _tier_model(tier: str) -> tuple[str, str, bool]:
    """返回 (模型, 说明, 是否因该层未配置而回落)。"""
    fallback = standard_model()
    if tier == TIER_LIGHT:
        if settings.llm_model_tier_light:
            return settings.llm_model_tier_light, "判定为简单问题，走轻量层", False
        return fallback, "LLM_MODEL_TIER_LIGHT 未配置，回落标准层", True
    if tier == TIER_REASONING:
        if settings.llm_model_tier_reasoning:
            return settings.llm_model_tier_reasoning, "判定为复杂问题，走旗舰层", False
        return fallback, "LLM_MODEL_TIER_REASONING 未配置，回落标准层", True
    return fallback, "判定为中等复杂度，走标准层", False


def decide(
    *, purpose: str = "", text: str = "", model: str = "",
    citation_count: int = 0, context_chars: int = 0,
) -> Decision:
    """算一次路由决策（不写审计）。`model` 非空表示调用方显式指定，路由不覆盖。"""
    purpose = (purpose or "").strip()
    score, signals = score_complexity(
        text, purpose=purpose, citation_count=citation_count, context_chars=context_chars,
    )
    complexity = complexity_for(score)

    if model:
        return Decision(
            purpose=purpose, tier=TIER_STANDARD, model=model, source="explicit-model",
            reason="调用方显式指定模型（专用模型），不做分层覆盖", score=score,
            complexity=complexity, signals=tuple(signals), routed=False, changed=False,
        )

    standard = standard_model()
    if purpose in DESIGNATED_PURPOSES:
        # 专用模型用途即使调用方没显式传 model（例如专用配置被运维置空），也不允许被分层覆盖：
        # "抽取 / 核查用哪个模型"是配置决定的事实，不是复杂度决定的。
        return Decision(
            purpose=purpose, tier=TIER_STANDARD, model=standard, source="designated-purpose",
            reason=f"用途 {purpose} 使用专用模型配置（{DESIGNATED_PURPOSES[purpose]}），不参与分层",
            score=score, complexity=complexity, signals=tuple(signals), routed=False, changed=False,
        )
    if not runtime_flags.enabled("model_routing"):
        return Decision(
            purpose=purpose, tier=TIER_STANDARD, model=standard, source="routing-disabled",
            reason="模型分层路由未启用（LLM_ROUTING_ENABLED=false 或运行时开关 model_routing 已关闭）",
            score=score, complexity=complexity, signals=tuple(signals), routed=False, changed=False,
        )
    if purpose not in ROUTABLE_PURPOSES and purpose not in DESIGNATED_PURPOSES:
        return Decision(
            purpose=purpose, tier=TIER_STANDARD, model=standard, source="purpose-not-routable",
            reason=f"用途 {purpose or '(未标注)'} 不在可分层用途清单内，保守走标准层",
            score=score, complexity=complexity, signals=tuple(signals), routed=False, changed=False,
        )

    tier = tier_for_score(score)
    selected, reason, fell_back = _tier_model(tier)
    source = "tier-model-unset" if fell_back else f"complexity-{complexity}"
    return Decision(
        purpose=purpose, tier=tier, model=selected, source=source, reason=reason,
        score=score, complexity=complexity, signals=tuple(signals),
        routed=not fell_back, changed=selected != standard,
    )


def _record(decision: Decision) -> None:
    """留痕：逐步进 `agent_run.steps`，汇总进 `agent_run.routing`。"""
    capture = current_run.get()
    # 超过上限后不再逐条写 step：否则"审计不被撑爆"只挡住了一半
    # （`run.steps` 仍会按调用次数增长），批量抽取这类场景会翻倍放大审计体积。
    if capture is None or len(capture.routing.get("decisions") or []) < MAX_DECISIONS:
        with step(
            "model.route",
            inputs={
                "purpose": decision.purpose, "complexity": decision.complexity,
                "score": decision.score, "signals": list(decision.signals),
            },
            model=decision.model,
        ) as record:
            record["output"] = decision.as_dict()

    if capture is None:
        return
    with capture.lock:
        summary = capture.routing
        summary["enabled"] = runtime_flags.enabled("model_routing")
        summary["tiers"][decision.tier] = summary["tiers"].get(decision.tier, 0) + 1
        summary["models"][decision.model] = summary["models"].get(decision.model, 0) + 1
        summary["sources"][decision.source] = summary["sources"].get(decision.source, 0) + 1
        if decision.changed:
            summary["routedCalls"] = summary.get("routedCalls", 0) + 1
        if len(summary["decisions"]) < MAX_DECISIONS:
            summary["decisions"].append(decision.as_dict())


def resolve(
    *, purpose: str = "", text: str = "", model: str = "",
    citation_count: int = 0, context_chars: int = 0,
) -> Decision:
    """算决策 + 写审计，返回决策。`llm.py` 的唯一入口。"""
    decision = decide(
        purpose=purpose, text=text, model=model,
        citation_count=citation_count, context_chars=context_chars,
    )
    _record(decision)
    return decision


def last_decision(purpose: str = "") -> dict | None:
    """当前运行里最近一条路由决策（可按用途取），供响应体与审计回填。"""
    capture = current_run.get()
    if capture is None:
        return None
    decisions = capture.routing.get("decisions") or []
    for item in reversed(decisions):
        if not purpose or item.get("purpose") == purpose:
            return item
    return None


def snapshot() -> dict:
    """路由能力现状（供运维端点展示：开关、阈值、三层模型是否已配置）。"""
    return {
        "enabled": runtime_flags.enabled("model_routing"),
        "configDefault": bool(settings.llm_routing_enabled),
        "source": "runtime-override" if runtime_flags.is_overridden("model_routing") else "configuration",
        "tiers": {
            "light": {"model": settings.llm_model_tier_light, "configured": bool(settings.llm_model_tier_light)},
            "standard": {
                "model": standard_model(),
                "configured": bool(settings.llm_model_tier_standard or settings.llm_model_generation),
            },
            "reasoning": {
                "model": settings.llm_model_tier_reasoning,
                "configured": bool(settings.llm_model_tier_reasoning),
            },
        },
        "thresholds": {
            "lightMaxScore": settings.llm_routing_light_max_score,
            "reasoningMinScore": settings.llm_routing_reasoning_min_score,
        },
        "routablePurposes": list(ROUTABLE_PURPOSES),
        "designatedPurposes": DESIGNATED_PURPOSES,
        "note": (
            "未配置轻量层 / 旗舰层模型时，开启路由开关也是 no-op（回落标准层），"
            "决策里会写明 source=tier-model-unset。"
        ),
    }