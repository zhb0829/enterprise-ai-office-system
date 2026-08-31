"""会议要点、纪要和知识卡片生成，所有结论保持来源引用。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import settings
from ..services.llm import LLMClient, LLMError

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
CARD_TYPES = {"核心观点", "决策事项", "行动项", "专家观点", "关键数据"}


def extract_insights(materials: list[dict]) -> list[dict]:
    evidence = _evidence(materials)
    if not evidence:
        return []
    llm = LLMClient()
    if not llm.is_mock:
        try:
            prompt = _prompt("extract.md").replace("{{evidence}}", json.dumps(evidence[:120], ensure_ascii=False))
            data = llm.chat_json([
                {"role": "system", "content": "你是公开行业会议研究员，只能依据给定资料提炼。"},
                {"role": "user", "content": prompt},
            ], model=settings.llm_model_extraction, temperature=0.1)
            return validate_insights(data.get("insights") or [], evidence)
        except (LLMError, ValueError, AttributeError):
            pass
    return _rule_insights(evidence)


def generate_report(conference: dict, insights: list[dict], media: list[dict]) -> tuple[str, str]:
    if not insights:
        return (
            f"# {conference.get('name', '会议')}会议纪要\n\n"
            "## 资料状态\n\n当前公开资料未提取到可核验要点，请补充可解析文件或转录文本后重新整理。",
            "rule-based",
        )
    llm = LLMClient()
    if not llm.is_mock:
        try:
            prompt = _prompt("report.md")
            prompt = prompt.replace("{{conference}}", json.dumps(conference, ensure_ascii=False, default=str))
            prompt = prompt.replace("{{insights}}", json.dumps(insights, ensure_ascii=False))
            prompt = prompt.replace("{{media}}", json.dumps(media[:20], ensure_ascii=False))
            content = llm.chat([
                {"role": "system", "content": "输出结构化 Markdown 会议纪要。每条要点必须保留输入中的引用标记。"},
                {"role": "user", "content": prompt},
            ], model=settings.meeting_report_model, temperature=0.2)
            if content.strip():
                return ensure_report_citations(content, insights), settings.meeting_report_model
        except LLMError:
            pass
    return _rule_report(conference, insights, media), "rule-based"


def generate_cards(insights: list[dict], existing_cards: list[dict]) -> list[dict]:
    generated = []
    for insight in insights:
        generated.append({
            "cardType": insight["cardType"],
            "title": insight["title"],
            "content": insight["content"],
            "actor": insight.get("actor", ""),
            "expectedTime": insight.get("expectedTime", ""),
            "sourceRef": insight["sourceRef"],
        })
    merged = []
    seen = set()
    for card in [*(existing_cards or []), *generated]:
        key = (
            str(card.get("cardType") or ""),
            _normalize_key(str(card.get("title") or "")),
            _normalize_key(str(card.get("content") or ""))[:120],
        )
        if key in seen:
            continue
        seen.add(key)
        refs = card.get("sourceRef") if isinstance(card.get("sourceRef"), list) else []
        if not refs:
            refs = [{"status": "待确认", "reason": "缺少来源引用"}]
            card["content"] = "【待确认】" + str(card.get("content") or "")
        merged.append({**card, "sourceRef": refs})
    return merged[:60]


def validate_insights(items: list[dict], evidence: list[dict]) -> list[dict]:
    known = {(item["materialId"], item["location"]) for item in evidence}
    result = []
    for raw in items:
        refs = []
        for ref in raw.get("sourceRef") or []:
            key = (int(ref.get("materialId") or 0), str(ref.get("location") or ""))
            if key in known:
                refs.append({
                    "materialId": key[0],
                    "location": key[1],
                    "quote": str(ref.get("quote") or "")[:500],
                })
        content = str(raw.get("content") or "").strip()
        if not refs:
            refs = [{"status": "待确认", "reason": "模型输出未命中已知资料位置"}]
            content = "【待确认】" + content
        card_type = str(raw.get("cardType") or "核心观点")
        result.append({
            "cardType": card_type if card_type in CARD_TYPES else "核心观点",
            "title": str(raw.get("title") or content[:30] or "会议要点")[:256],
            "content": content,
            "actor": str(raw.get("actor") or "")[:256],
            "expectedTime": str(raw.get("expectedTime") or "")[:128],
            "sourceRef": refs,
        })
    return result[:50]


def ensure_report_citations(content: str, insights: list[dict]) -> str:
    if re.search(r"\[资料#\d+", content):
        return content
    lines = [content.rstrip(), "", "## 来源索引"]
    for insight in insights:
        lines.append(f"- {insight['title']} {_citation(insight['sourceRef'][0])}")
    return "\n".join(lines)


def _evidence(materials: list[dict]) -> list[dict]:
    result = []
    for material in materials:
        if material.get("parseStatus") != "parsed":
            continue
        parse_result = material.get("parseResult") or {}
        for segment in parse_result.get("segments") or []:
            text = str(segment.get("text") or "").strip()
            if text:
                result.append({
                    "materialId": int(material.get("id") or 0),
                    "materialTitle": str(material.get("title") or ""),
                    "location": str(segment.get("location") or "原文"),
                    "speaker": str(segment.get("speaker") or ""),
                    "text": text[:1600],
                })
    return result


def _rule_insights(evidence: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for item in evidence:
        sentences = [part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*", item["text"]) if len(part.strip()) >= 12]
        for sentence in sentences[:3]:
            key = _normalize_key(sentence)[:100]
            if key in seen:
                continue
            seen.add(key)
            card_type = _card_type(sentence, item.get("speaker", ""))
            result.append({
                "cardType": card_type,
                "title": _title(sentence),
                "content": sentence,
                "actor": item.get("speaker", "") if card_type in {"专家观点", "行动项"} else "",
                "expectedTime": _expected_time(sentence),
                "sourceRef": [{
                    "materialId": item["materialId"],
                    "location": item["location"],
                    "quote": sentence[:300],
                }],
            })
            if len(result) >= 30:
                return result
    return result


def _rule_report(conference: dict, insights: list[dict], media: list[dict]) -> str:
    grouped = {card_type: [] for card_type in CARD_TYPES}
    for item in insights:
        grouped.setdefault(item["cardType"], []).append(item)
    lines = [
        f"# {conference.get('name', '会议')}会议纪要",
        "",
        "## 会议信息",
        "",
        f"- 类型：{conference.get('category') or '未提供'}",
        f"- 时间：{conference.get('startTime') or '未提供'}",
        f"- 地点：{conference.get('location') or '未提供'}",
        f"- 主办方：{conference.get('organizer') or '未提供'}",
        "",
        "## 核心观点",
        "",
    ]
    core = grouped.get("核心观点", []) + grouped.get("专家观点", [])
    lines.extend(f"- {item['content']} {_citation(item['sourceRef'][0])}" for item in core[:12])
    for title, card_type in (("决策事项", "决策事项"), ("行动项", "行动项"), ("关键数据", "关键数据")):
        lines.extend(["", f"## {title}", ""])
        values = grouped.get(card_type, [])
        lines.extend(f"- {item['content']} {_citation(item['sourceRef'][0])}" for item in values[:10])
        if not values:
            lines.append("- 暂未从公开资料中提取到可核验内容。")
    lines.extend(["", "## 相关公开报道", ""])
    if media:
        lines.extend(f"- {item.get('title')}（{item.get('sourceName') or '公开来源'}）" for item in media[:10])
    else:
        lines.append("- 暂未采集到关键词命中的 RSS 补充报道。")
    return "\n".join(lines)


def _card_type(text: str, speaker: str) -> str:
    if re.search(r"\d+(?:\.\d+)?%|亿元|万亿元|同比|增长|下降|数量|规模", text):
        return "关键数据"
    if re.search(r"决定|通过|发布|正式实施|明确要求", text):
        return "决策事项"
    if re.search(r"将|计划|推进|加快|开展|落实|下一步|目标", text):
        return "行动项"
    if speaker:
        return "专家观点"
    return "核心观点"


def _expected_time(text: str) -> str:
    match = re.search(r"(20\d{2}年(?:\d{1,2}月)?|未来\d+[年月]|下一阶段|近期|年底前)", text)
    return match.group(1) if match else ""


def _title(text: str) -> str:
    cleaned = re.sub(r"\s+", "", text)
    return cleaned[:28] + ("…" if len(cleaned) > 28 else "")


def _citation(ref: dict) -> str:
    if ref.get("materialId"):
        return f"[资料#{ref['materialId']} {ref.get('location') or '原文'}]"
    return "[待确认]"


def _normalize_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower())


def _prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")
