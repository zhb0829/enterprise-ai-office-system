"""LangGraph 五步会议整理编排与步骤级重试。"""
from __future__ import annotations

import logging
import time
from typing import TypedDict

from langgraph.graph import END, StateGraph

from ..db import SessionLocal
from ..services.materials import embed_texts
from .collector import collect_rss
from .generation import extract_insights, generate_cards, generate_report
from .java_client import java_client
from .models_ai import MeetingKnowledgeIndex
from .parsers import parse_material
from .recommendation import recommend

logger = logging.getLogger(__name__)
STEPS = [
    ("collect", "采集补充报道"),
    ("parse", "解析多模态资料"),
    ("extract", "提炼会议要点"),
    ("generate", "生成纪要与知识卡片"),
    ("recommend", "关联政策与历史会议"),
]


class MeetingState(TypedDict, total=False):
    task_id: int
    conference: dict
    materials: list[dict]
    existing_cards: list[dict]
    steps: list[dict]
    media: list[dict]
    insights: list[dict]
    report: str
    model: str
    cards: list[dict]
    related_policies: list[dict]
    related_conferences: list[dict]


def build_graph():
    graph = StateGraph(MeetingState)
    graph.add_node("collect", _collect)
    graph.add_node("parse", _parse)
    graph.add_node("extract", _extract)
    graph.add_node("generate", _generate)
    graph.add_node("recommend", _recommend)
    graph.set_entry_point("collect")
    graph.add_edge("collect", "parse")
    graph.add_edge("parse", "extract")
    graph.add_edge("extract", "generate")
    graph.add_edge("generate", "recommend")
    graph.add_edge("recommend", END)
    return graph.compile()


def initial_state(task_id: int, payload: dict) -> MeetingState:
    steps = []
    for key, label in STEPS:
        steps.append({
            "step": key,
            "label": label,
            "status": "pending",
            "elapsedMs": 0,
            "error": "",
        })
    return {
        "task_id": task_id,
        "conference": payload.get("conference") or {},
        "materials": [dict(item) for item in payload.get("materials") or []],
        "existing_cards": payload.get("existingCards") or [],
        "steps": steps,
        "media": [],
        "insights": [],
    }


def run_job(task_id: int, payload: dict) -> dict:
    state = initial_state(task_id, payload)
    try:
        result = build_graph().invoke(state)
        response = {
            "model": result.get("model", "rule-based"),
            "report": {
                "content": result.get("report", ""),
                "relatedPolicies": result.get("related_policies", []),
                "relatedConferences": result.get("related_conferences", []),
            },
            "cards": result.get("cards", []),
            "media": result.get("media", []),
            "materials": _material_updates(result.get("materials", [])),
            "steps": result.get("steps", []),
        }
        java_client.result(task_id, response)
        _index_cards(int(result.get("conference", {}).get("id") or 0), result.get("cards", []))
        return response
    except Exception as exc:  # noqa: BLE001
        logger.exception("会议整理任务失败 task_id=%s", task_id)
        try:
            java_client.failure(task_id, str(exc))
        except Exception:  # noqa: BLE001
            logger.exception("会议整理失败回调未送达 task_id=%s", task_id)
        raise


def _collect(state: MeetingState) -> MeetingState:
    return _run_step(state, "collect", lambda: state.update(media=collect_rss(state["conference"])))


def _parse(state: MeetingState) -> MeetingState:
    def action():
        state["materials"] = [parse_material(item) for item in state["materials"]]
        if not any(item.get("parseStatus") == "parsed" for item in state["materials"]):
            errors = [str((item.get("parseResult") or {}).get("error") or "") for item in state["materials"]]
            raise ValueError("没有可用于生成纪要的资料：" + "；".join(filter(None, errors))[:1000])
    return _run_step(state, "parse", action)


def _extract(state: MeetingState) -> MeetingState:
    return _run_step(state, "extract", lambda: state.update(insights=extract_insights(state["materials"])))


def _generate(state: MeetingState) -> MeetingState:
    def action():
        report, model = generate_report(state["conference"], state["insights"], state["media"])
        state["report"] = report
        state["model"] = model
        state["cards"] = generate_cards(state["insights"], state.get("existing_cards") or [])
    return _run_step(state, "generate", action)


def _recommend(state: MeetingState) -> MeetingState:
    def action():
        policies, conferences = recommend(state["conference"], state["report"])
        state["related_policies"] = policies
        state["related_conferences"] = conferences
    return _run_step(state, "recommend", action)


def _run_step(state: MeetingState, step_key: str, action) -> MeetingState:
    step = next(item for item in state["steps"] if item["step"] == step_key)
    last_error = None
    for attempt in range(3):
        started = time.perf_counter()
        step.update(status="running", error="", attempt=attempt + 1)
        java_client.progress(state["task_id"], state["steps"], state["materials"])
        try:
            action()
            step.update(
                status="completed",
                elapsedMs=round((time.perf_counter() - started) * 1000),
                error="",
            )
            java_client.progress(state["task_id"], state["steps"], state["materials"])
            return state
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            step.update(status="retrying" if attempt < 2 else "failed", error=str(exc)[:1000])
            java_client.progress(state["task_id"], state["steps"], state["materials"], status="partial")
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{step['label']}失败：{last_error}") from last_error


def _material_updates(materials: list[dict]) -> list[dict]:
    return [{
        "id": item.get("id"),
        "parseStatus": item.get("parseStatus", "pending"),
        "parseResult": item.get("parseResult") or {},
    } for item in materials]


def _index_cards(conference_id: int, cards: list[dict]) -> None:
    if not conference_id or not cards:
        return
    db = SessionLocal()
    try:
        db.query(MeetingKnowledgeIndex).filter(MeetingKnowledgeIndex.conference_id == conference_id).delete()
        texts = [f"{item.get('title', '')}\n{item.get('content', '')}" for item in cards]
        vectors = embed_texts(texts)
        for item, vector in zip(cards, vectors):
            db.add(MeetingKnowledgeIndex(
                conference_id=conference_id,
                card_type=str(item.get("cardType") or ""),
                title=str(item.get("title") or ""),
                content=str(item.get("content") or ""),
                embedding=vector,
                source_ref=item.get("sourceRef") or [],
            ))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("会议知识卡片向量索引写入失败 conference_id=%s", conference_id)
    finally:
        db.close()
