"""LangGraph 状态图编排：抽取 → 必填校验 → 多文风并行生成 → 建议输出。

- 必填校验失败 → 条件边走 END，由路由层将 missing 返回为 422。
- 多文风并行：ThreadPoolExecutor 并行调用 LLM 生成各文风版本。
- 业务节点全部自研；LLM 可插拔（LLMClient）。
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from ..services.extraction import extract_elements, validate_required
from ..services.generation import check_risks, generate_content, suggest_content
from ..services.llm import LLMClient

logger = logging.getLogger(__name__)


class DraftState(TypedDict, total=False):
    request: dict
    template: dict
    materials: str
    elements: list
    missing: list
    drafts: list
    suggestions: list
    risk_flags: list
    fact_check_report: list


def check_required_node(state: DraftState) -> dict:
    missing = validate_required(state.get("request", {}), state.get("template", {}))
    return {"missing": missing}


def extract_node(state: DraftState, llm: LLMClient) -> dict:
    elements = extract_elements(state.get("request", {}), state.get("template", {}), llm)
    return {"elements": elements}


def generate_node(state: DraftState, llm: LLMClient) -> dict:
    """多文风并行生成。"""
    from ..services.generation import _resolve_styles

    request = state.get("request", {})
    template = state.get("template", {})
    elements = state.get("elements", [])
    materials = state.get("materials", "")
    styles = _resolve_styles(request)

    def _gen(style: str) -> dict:
        try:
            content = generate_content(request, template, elements, style, materials, llm)
            return {"style": style, "content": content}
        except Exception as exc:  # noqa: BLE001
            logger.error("生成失败 [%s]: %s", style, exc)
            return {"style": style, "content": "", "error": str(exc)}

    with ThreadPoolExecutor(max_workers=min(len(styles), 5)) as ex:
        drafts = list(ex.map(_gen, styles))
    return {"drafts": drafts}


def suggest_node(state: DraftState, llm: LLMClient) -> dict:
    drafts = state.get("drafts") or []
    main = next((d for d in drafts if d.get("content") and not d.get("error")), {})
    suggestions = suggest_content(state.get("request", {}), state.get("template", {}), main, llm)
    risk_flags = check_risks(state.get("request", {}))
    return {"suggestions": suggestions, "risk_flags": risk_flags}


def factcheck_node(state: DraftState, llm: LLMClient) -> dict:
    """对主风格草稿执行事实核查，返回核查报告。"""
    from ..services.factcheck import run_factcheck

    drafts = state.get("drafts") or []
    main = next((d for d in drafts if d.get("content") and not d.get("error")), {})
    report = run_factcheck(
        main.get("content", ""),
        state.get("elements") or [],
        state.get("materials", ""),
        llm,
    )
    return {"fact_check_report": report}


def _route_after_check(state: DraftState) -> str:
    return "ok" if not state.get("missing") else "missing"


def build_draft_graph(llm: LLMClient):
    graph = StateGraph(DraftState)
    graph.add_node("check_required", check_required_node)
    graph.add_node("extract", lambda s: extract_node(s, llm))
    graph.add_node("generate", lambda s: generate_node(s, llm))
    graph.add_node("factcheck", lambda s: factcheck_node(s, llm))
    graph.add_node("suggest", lambda s: suggest_node(s, llm))

    graph.add_edge(START, "check_required")
    graph.add_conditional_edges(
        "check_required",
        _route_after_check,
        {"ok": "extract", "missing": END},
    )
    graph.add_edge("extract", "generate")
    graph.add_edge("generate", "factcheck")
    graph.add_edge("factcheck", "suggest")
    graph.add_edge("suggest", END)
    return graph.compile()


# ===== 多轮修改图：修订生成 → 差异说明 =====

class RevisionState(TypedDict, total=False):
    base: object  # Draft 对象（原版本）
    instruction: str
    new_content: str
    diff: list
    elements: list  # 版本要素（原稿继承）
    materials: str  # 参考素材文本
    fact_check_report: list


def revise_node(state: RevisionState, llm: LLMClient) -> dict:
    from ..services.revise import revise_content

    content = revise_content(state["base"], state["instruction"], llm, state.get("materials", ""))
    return {"new_content": content}


def diff_node(state: RevisionState, llm: LLMClient) -> dict:
    from ..services.revise import diff_summary

    diff = diff_summary(state["base"], state.get("new_content", ""), state["instruction"], llm)
    return {"diff": diff}


def revision_factcheck_node(state: RevisionState, llm: LLMClient) -> dict:
    from ..services.factcheck import run_factcheck

    report = run_factcheck(
        state.get("new_content", ""),
        state.get("elements") or [],
        state.get("materials", ""),
        llm,
    )
    return {"fact_check_report": report}


def build_revision_graph(llm: LLMClient):
    graph = StateGraph(RevisionState)
    graph.add_node("revise", lambda s: revise_node(s, llm))
    graph.add_node("diff", lambda s: diff_node(s, llm))
    graph.add_node("factcheck", lambda s: revision_factcheck_node(s, llm))
    graph.add_edge(START, "revise")
    graph.add_edge("revise", "diff")
    graph.add_edge("diff", "factcheck")
    graph.add_edge("factcheck", END)
    return graph.compile()
