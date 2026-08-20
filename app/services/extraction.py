"""要素结构化抽取。

- 必填校验：当前不按模板 placeholders 阻断生成，由用户填写的要素直接参与生成。
- 要素抽取：有 Key 时用 LLM 从事件描述提炼时间/地点/事件要点；Mock 模式规则化兜底。
  用户显式提供的要素 verified_status=来自用户输入；LLM 抽取的标记为待核实。
"""
import logging

from ..config import settings
from .llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

_EVENT = "eventDesc"
_AUDIENCE = "audience"
_PEOPLE = "people"
_KEYS_ANY = "keyFactsAny"
_TITLE = "title"
_KEYFACTS_PREFIX = "keyFacts:"


def validate_required(request: dict, template: dict) -> list[str]:
    """保留接口形状，但不再按模板必填项阻断生成。"""
    return []


def extract_elements(request: dict, template: dict, llm: LLMClient) -> list[dict]:
    """抽取结构化要素，返回 [{name, value, source_ref, verified_status}]。

    顺序：LLM 从事件描述抽取的要点在前，用户显式要素（keyFacts/people/audience）在后。
    """
    elements: list[dict] = []
    for k in request.get("keyFacts") or []:
        if k.get("value"):
            elements.append(
                {"name": k["name"], "value": k["value"], "source_ref": "用户输入要素", "verified_status": "来自用户输入"}
            )
    for p in request.get("people") or []:
        if p.get("name"):
            title = f"（{p['title']}）" if p.get("title") else ""
            elements.append(
                {"name": f"人物:{p['name']}", "value": f"{p['name']}{title}", "source_ref": "用户输入人物", "verified_status": "来自用户输入"}
            )
    if (request.get(_AUDIENCE) or "").strip():
        elements.append({"name": "受众", "value": request["audience"], "source_ref": "用户输入", "verified_status": "来自用户输入"})

    if llm.is_mock:
        elements.insert(0, {"name": "事件", "value": request.get(_EVENT, ""), "source_ref": "用户事件描述", "verified_status": "来自用户输入"})
        return elements

    # 用轻量模型从事件描述抽取要点（失败不阻塞，退回规则化）
    try:
        sys_p = (
            "你是企业文书要素抽取器。从给定的事件描述中抽取结构化要素。"
            '只输出 JSON 对象：{"elements":[{"name":"要素名","value":"要素值"}]}。'
            "只抽取明确出现的内容，禁止编造未提及的时间、地点、数字、人名。"
        )
        user_p = f"事件描述：{request.get(_EVENT, '')}\n文档类别：{template.get('title', '')}"
        data = llm.chat_json(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
            model=settings.llm_model_extraction,
            temperature=0,
        )
        for e in data.get("elements", []):
            if e.get("name") and e.get("value"):
                elements.insert(
                    0,
                    {"name": e["name"], "value": e["value"], "source_ref": "事件描述抽取", "verified_status": "待核实"},
                )
    except (LLMError, ValueError, AttributeError) as exc:
        logger.warning("要素抽取失败，退回规则化: %s", exc)
        elements.insert(0, {"name": "事件", "value": request.get(_EVENT, ""), "source_ref": "用户事件描述", "verified_status": "来自用户输入"})
    return elements
