"""资质编制任务的 Worker 实现。"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import settings
from .llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

_LLM = LLMClient()

MATERIAL_PER_FILE_LIMIT = 6000
MATERIAL_TOTAL_LIMIT = 24000


def build_document(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """基于指南结构和已上传档案生成可追溯的初稿。"""
    guide = payload.get("guide") or {}
    schema = guide.get("schema") or {}
    sections = schema.get("sections") or []
    materials = payload.get("materials") or []
    guide_title = str(guide.get("guideName") or "资质申报指南")
    qualification_type = str(payload.get("qualificationType") or "企业资质")
    document_type = str(payload.get("documentType") or "资质申报材料初稿")

    sources = [
        {
            "id": f"guide:{guide.get('id', 'unknown')}",
            "docTitle": guide_title,
            "excerpt": f"已锁定指南版本：{guide.get('version') or 'v1'}",
            "score": 1.0,
        }
    ]
    for material in materials:
        text = str(material.get("text") or "").strip()
        sources.append(
            {
                "id": f"material:{material.get('id', 'unknown')}",
                "docTitle": str(material.get("fileName") or "企业档案"),
                "excerpt": text[:240] or "企业档案已上传，未提供可引用正文。",
                "score": 1.0,
            }
        )

    material_texts = [
        (str(material.get("fileName") or "企业档案"), str(material.get("text") or "").strip())
        for material in materials
        if str(material.get("text") or "").strip()
    ]
    source_ids = [source["id"] for source in sources]

    section_titles = [
        str(section.get("title") or section.get("name") or f"第 {index} 部分")
        for index, section in enumerate(sections, start=1)
    ]
    llm_contents = _llm_draft_sections(section_titles, guide_title, document_type, qualification_type, material_texts)

    drafted_sections = []
    for index, section in enumerate(sections, start=1):
        title = section_titles[index - 1]
        content = llm_contents.get(str(section.get("key") or "")) or llm_contents.get(title) or _section_text(
            title, guide_title, material_texts
        )
        paragraphs = _drop_leading_heading(_split_paragraphs(content), title)
        drafted_sections.append(
            {
                "key": str(section.get("key") or f"section_{index}"),
                "name": title,
                "title": title,
                "required": bool(section.get("required", True)),
                "blocks": [
                    {
                        "type": "text",
                        "text": paragraph,
                        "citations": [{"id": source_id} for source_id in source_ids],
                    }
                    for paragraph in paragraphs
                ],
            }
        )

    if not drafted_sections:
        drafted_sections.append(
            {
                "key": "main",
                "name": "申报要求",
                "title": "申报要求",
                "required": True,
                "blocks": [
                    {
                        "type": "text",
                        "text": f"本材料依据《{guide_title}》整理，具体内容应由审核人员结合已上传企业档案核对后确认。",
                        "citations": [{"id": source_id} for source_id in source_ids],
                    }
                ],
            }
        )

    return (
        {
            "title": f"{qualification_type}{document_type}",
            "sections": drafted_sections,
        },
        sources,
        [],
    )


def _llm_draft_sections(
    section_titles: list[str],
    guide_title: str,
    document_type: str,
    qualification_type: str,
    material_texts: list[tuple[str, str]],
) -> dict[str, str]:
    """调用 LLM 逐章撰写；返回 章节key/标题 -> 正文 的映射，失败返回空 dict 走规则兜底。"""
    if _LLM.is_mock or not section_titles or "PYTEST_CURRENT_TEST" in os.environ:
        return {}
    numbered = "\n".join(f"{index}. {title}" for index, title in enumerate(section_titles, start=1))
    material_blocks = []
    total = 0
    for name, text in material_texts:
        clipped = text[:MATERIAL_PER_FILE_LIMIT]
        material_blocks.append(f"【档案：{name}】\n{clipped}")
        total += len(clipped)
        if total >= MATERIAL_TOTAL_LIMIT:
            break
    materials_text = "\n\n".join(material_blocks) or "（未上传企业档案，请依据指南要求撰写框架性内容，并将缺失信息标注为「待人工补充」）"
    system = (
        "你是资质申报与业务文档撰写助手。只能依据用户提供的指南要求和企业档案撰写内容，"
        "不得编造档案中不存在的数据、案例或承诺；档案信息不足的部分写明「待人工补充」。"
        "语言正式、具体，避免空话套话，禁止在多个章节重复相同段落。"
    )
    user = (
        f"请为《{guide_title}》（{qualification_type}，输出文档类型：{document_type}）撰写以下 {len(section_titles)} 个章节的正文。\n"
        f"章节列表：\n{numbered}\n\n"
        f"企业档案材料：\n{materials_text}\n\n"
        "要求：\n"
        "1. 每个章节写 1-3 段连贯正文，段落之间用两个换行分隔；\n"
        "2. 各章节只写与本章节标题相关的内容，引用档案中的具体事实、数字和案例；\n"
        "3. 正文直接从内容开始，不要重复章节标题，不要输出「本节」之类的元描述；\n"
        "4. 严格输出 JSON，格式：{\"sections\": [{\"section\": 章节序号(数字), \"content\": \"该章节正文\"}]}，按章节顺序覆盖全部章节。"
    )
    try:
        data = _LLM.chat_json(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("资质初稿 LLM 生成失败，回退规则模板：%s", exc)
        return {}
    contents: dict[str, str] = {}
    items = data.get("sections")
    if not isinstance(items, list):
        return {}
    for item in items:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        try:
            position = int(item.get("section"))
        except (TypeError, ValueError):
            continue
        if 1 <= position <= len(section_titles):
            title = section_titles[position - 1]
            contents[title] = content
            for index, section_title in enumerate(section_titles, start=1):
                if section_title == title:
                    contents[f"section_{index}"] = content
    return contents


def _split_paragraphs(content: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content or "") if part.strip()]
    return paragraphs or [(content or "").strip() or "待人工补充。"]


_HEADING_PREFIX = re.compile(r"^[（(]?[一二三四五六七八九十百\d]{1,3}[、.．,)）]?\s*\S{1,30}$")


def _looks_like_heading(paragraph: str, title: str) -> bool:
    text = re.sub(r"\s+", "", paragraph)
    if not text or len(text) > 30:
        return False
    return text == re.sub(r"\s+", "", title) or text.startswith(re.sub(r"\s+", "", title)) or bool(_HEADING_PREFIX.match(text))


def _drop_leading_heading(paragraphs: list[str], title: str) -> list[str]:
    if len(paragraphs) > 1 and _looks_like_heading(paragraphs[0], title):
        return paragraphs[1:]
    return paragraphs


def _section_text(title: str, guide_title: str, material_texts: list[tuple[str, str]]) -> str:
    """规则兜底：优先摘取与章节标题关键词最相关的档案段落，避免各章节内容雷同。"""
    keywords = [token for token in re.split(r"[、，。：：\s（）()]+", title) if len(token) >= 2]
    best: tuple[int, str, str] | None = None
    for filename, text in material_texts:
        for paragraph in re.split(r"\n+", text):
            paragraph = paragraph.strip()
            if len(paragraph) < 30:
                continue
            score = sum(1 for keyword in keywords if keyword in paragraph)
            if score and (best is None or score > best[0]):
                best = (score, filename, paragraph)
    if best:
        return f"本节“{title}”依据《{guide_title}》及企业档案《{best[1]}》整理，相关内容：{best[2]}"
    if material_texts:
        filename, text = material_texts[0]
        excerpt = " ".join(text.split())[:700]
        return f"本节“{title}”依据《{guide_title}》及企业档案《{filename}》整理。可供核对的档案内容如下：{excerpt}"
    return f"本节“{title}”依据《{guide_title}》整理。请审核人员结合企业实际情况和申报要求核对、完善后使用。"


def send_callback(path: str, payload: dict[str, Any]) -> None:
    headers = {"X-Internal-Token": settings.ai_internal_token}
    with httpx.Client(timeout=30.0) as client:
        response = client.post(f"{settings.qual_java_base_url.rstrip('/')}{path}", json=payload, headers=headers)
        response.raise_for_status()


def process_task(payload: dict[str, Any]) -> None:
    task_id = str(payload["taskId"])
    idempotency_key = str(payload["idempotencyKey"])
    base = {
        "protocolVersion": str(payload.get("protocolVersion") or "1.0"),
        "taskId": task_id,
        "idempotencyKey": idempotency_key,
    }
    try:
        send_callback(
            "/internal/qual/progress",
            {**base, "phase": "GENERATING", "progress": 40, "message": "正在依据指南和企业档案生成初稿"},
        )
        document, sources, risk_flags = build_document(payload)
        send_callback(
            "/internal/qual/progress",
            {**base, "phase": "GENERATING", "progress": 80, "message": "章节内容撰写完成，正在汇总初稿"},
        )
        send_callback(
            "/internal/qual/result",
            {
                **base,
                "status": "complete",
                "document": document,
                "sources": sources,
                "riskFlags": risk_flags,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "model": "llm-qualification-drafter" if not _LLM.is_mock else "rule-based-qualification-drafter",
            },
        )
    except Exception as exc:  # noqa: BLE001
        try:
            send_callback("/internal/qual/failure", {**base, "message": f"资质初稿生成失败：{exc}"})
        except Exception:
            # 回调服务不可用时只能由 Worker 日志保留原始异常。
            pass
        raise
