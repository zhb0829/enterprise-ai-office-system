"""事实核查：断言抽取 → 与用户要素比对 → 与参考素材比对 → 核查报告。

输出断言判定（一致/不一致/无法核实）+ 依据 + 建议；"无法核实"不得默认放行，
由路由层合并进 riskFlags，前端负责正文高亮。
核查范围：数字/金额/百分比、日期、人名/头衔、机构名、地名、引用数据。
"""
import logging
import re

from ..config import settings
from ..agent.runtime import current_run, traced
from ..agent.runtime_flags import enabled as flag_enabled
from .llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

FACTCHECK_SYSTEM_PROMPT = (
    "你是企业稿件事实核查员。基于给定的【用户要素】与【参考素材】，逐条核验草稿中的事实断言。\n"
    "判定规则：\n"
    "- 一致：断言中的事实能在用户要素或参考素材中直接找到相同表述/数值。\n"
    "- 不一致：断言与用户要素或参考素材中的对应事实冲突（数值、日期、人名、机构名不一致）。\n"
    "- 无法核实：断言中的关键事实（数字、日期、人名、机构、地名）在用户要素与参考素材中均无依据。\n"
    '只输出 JSON 对象：{"report":[{"claim":"断言","status":"一致|不一致|无法核实","basis":"依据/来源","suggestion":"建议"}]}。\n'
    "每条断言必须给出明确判定，不得遗漏。"
)

CLAIM_EXTRACTION_PROMPT = (
    "从给定的稿件中抽取所有包含关键事实的断言短句（每个断言一句话，含数字/金额/百分比、日期、"
    "人名/头衔、机构名、地名、引用数据等）。\n"
    '只输出 JSON 对象：{"claims":["断言1","断言2"]}。'
)

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_HINT_RE = re.compile(r"(\d+(?:\.\d+)?(?:[%％万亿年月日号点半]|月份|万元|亿元|万)?|CEO|公司|集团|有限公司|研究院|大学|中心)")


def extract_claims(text: str, llm: LLMClient) -> list[str]:
    """抽取事实断言短句。"""
    if llm.is_mock:
        return _mock_extract_claims(text)
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": CLAIM_EXTRACTION_PROMPT},
                {"role": "user", "content": text},
            ],
            model=settings.llm_model_factcheck,
            temperature=0,
            purpose="factcheck",
        )
        return [str(c) for c in (data.get("claims") or []) if str(c).strip()]
    except (LLMError, ValueError, AttributeError) as exc:
        logger.warning("断言抽取失败: %s", exc)
        return _mock_extract_claims(text)


def verify_claims(claims: list[str], elements: list[dict], materials: str, llm: LLMClient) -> list[dict]:
    """逐条核验断言，返回核查报告。"""
    if llm.is_mock:
        return _mock_verify(claims, elements, materials)
    try:
        payload = {
            "用户要素": [{"name": e.get("name", ""), "value": e.get("value", "")} for e in elements],
            "参考素材": materials or "（无）",
            "待核验断言": claims,
        }
        import json

        data = llm.chat_json(
            [
                {"role": "system", "content": FACTCHECK_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            model=settings.llm_model_factcheck,
            temperature=0,
            purpose="factcheck",
        )
        report = []
        for item in data.get("report") or []:
            if not isinstance(item, dict) or not item.get("claim"):
                continue
            status = str(item.get("status", "无法核实"))
            if status not in ("一致", "不一致", "无法核实"):
                status = "无法核实"
            report.append(
                {
                    "claim": str(item["claim"]),
                    "status": status,
                    "basis": str(item.get("basis", "")),
                    "suggestion": str(item.get("suggestion", "")),
                }
            )
        return report
    except (LLMError, ValueError, AttributeError) as exc:
        logger.warning("事实核查失败，退回规则化: %s", exc)
        return _mock_verify(claims, elements, materials)


@traced("announcement.verify", prompt_version="factcheck-v2")
def run_factcheck(content: str, elements: list[dict], materials: str, llm: LLMClient) -> list[dict]:
    """完整核查流程：抽取断言 → 逐条核验。

    G5 运行时开关 `factcheck` 关闭时，整条链路退化为规则化核查，
    并在每条结果与 AgentRun 审计里明确标记 `degraded`，不冒充"已核查通过"。
    """
    if not content:
        return []
    factcheck_enabled = flag_enabled("factcheck")
    if factcheck_enabled:
        claims = list(dict.fromkeys([*extract_claims(content, llm), *_mock_extract_claims(content)]))
    else:
        logger.warning("模型事实核查已被运行时开关关闭，退化为规则化核查")
        claims = list(dict.fromkeys(_mock_extract_claims(content)))
    if not claims:
        return []
    if factcheck_enabled:
        proposed = {item["claim"]: item for item in verify_claims(claims, elements, materials, llm) if item["claim"] in claims}
    else:
        proposed = {item["claim"]: item for item in _mock_verify(claims, elements, materials)}
    report = []
    for claim in claims:
        item = proposed.get(claim, {"claim": claim, "status": "无法核实", "basis": "模型遗漏核查", "suggestion": "请补充证据"})
        item["evidence"] = evidence_for_claim(claim, elements, materials)
        if item["status"] == "一致" and not item["evidence"]:
            item.update(status="无法核实", basis="没有可定位的完整事实证据", suggestion="补充支持断言的原始来源后重新生成")
        if not factcheck_enabled:
            item["degraded"] = True
            item["degradeReason"] = "runtime-flag-factcheck-off"
        report.append(item)
    capture = current_run.get()
    if capture:
        capture.verification = {
            "fact_check_report": report,
            "evidence_coverage": sum(bool(item["evidence"]) for item in report) / len(report) if report else 0,
            "factcheck": {
                "enabled": factcheck_enabled,
                "degraded": not factcheck_enabled,
                "reason": "" if factcheck_enabled else "runtime-flag-factcheck-off",
            },
        }
    return report


def evidence_for_claim(claim: str, elements: list[dict], materials: str) -> list[dict]:
    """Only exact excerpts are proof; matching scattered numbers is not."""
    sources = []
    for index, element in enumerate(elements):
        value = str(element.get("value") or "")
        if claim in value and element.get("verified_status") != "待核实":
            sources.append({
                "kind": "user_input", "field": element.get("name", ""), "elementIndex": index,
                "sourceRef": element.get("source_ref", ""), "excerpt": claim,
                "start": value.index(claim), "end": value.index(claim) + len(claim),
            })
    for part in re.split(r"(?=\[素材:)", materials or ""):
        header, _, text = part.partition("\n")
        if claim in text:
            start = text.index(claim)
            sources.append({
                "kind": "material", "sourceRef": header.strip("[]"), "excerpt": claim,
                "start": start, "end": start + len(claim),
            })
    return sources


# ===== Mock 规则化实现（无 Key 兜底） =====
def _split_sentences(text: str) -> list[str]:
    sentences = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s+", "", line).replace("**", "").strip()
        for s in re.split(r"[。！？\n]", line):
            s = s.strip()
            if len(s) >= 6:
                sentences.append(s)
    return sentences


def _mock_extract_claims(text: str) -> list[str]:
    claims = []
    for s in _split_sentences(text):
        if _HINT_RE.search(s):
            claims.append(s)
    return claims


def _mock_verify(claims: list[str], elements: list[dict], materials: str) -> list[dict]:
    element_text = " ".join((e.get("value") or "") for e in elements)
    material_text = materials or ""
    people_values = [e.get("value", "") for e in elements if str(e.get("name", "")).startswith("人物")]
    report = []
    for claim in claims:
        nums = set(_NUM_RE.findall(claim))
        names = [v for v in people_values if v.split("（")[0] in claim]
        if nums:
            if nums.issubset(set(_NUM_RE.findall(element_text))):
                status, basis = "一致", "与用户输入要素一致"
            elif nums.issubset(set(_NUM_RE.findall(material_text))):
                status, basis = "一致", "与参考素材一致"
            else:
                status, basis = "无法核实", "要素与素材中均无此数字依据"
        elif names:
            status, basis = "一致", f"与人物要素一致（{names[0]}）"
        elif any(org in claim for org in ("公司", "集团", "有限公司", "研究院", "大学")):
            if org_in_elements(claim, element_text):
                status, basis = "一致", "与用户输入要素一致"
            else:
                status, basis = "无法核实", "要素中无对应机构信息"
        else:
            status, basis = "无法核实", "缺少可核实的数字/人名/机构依据"
        suggestion = "无需修改" if status == "一致" else "请补充要素或标注【待核实】后人工确认"
        report.append({"claim": claim, "status": status, "basis": basis, "suggestion": suggestion})
    return report


def org_in_elements(claim: str, element_text: str) -> bool:
    # 将断言中的机构关键词与要素文本做宽松匹配
    for token in re.findall(r"[\u4e00-\u9fa5]{2,12}?(?:公司|集团|有限公司|研究院|大学|中心)", claim):
        if token in element_text:
            return True
    return False
