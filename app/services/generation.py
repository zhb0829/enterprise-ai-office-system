"""生成链路业务核心：prompt 构建、mock 生成、素材注入、敏感词检查、草稿持久化。"""
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Draft, DraftElement, FactCheck, ReferenceMaterial, Template
from .llm import LLMClient, LLMError
from .template_loader import load_styles

logger = logging.getLogger(__name__)

# 轻量前置敏感词（生成前风险扫描）
RISK_WORDS = ["非法", "传销", "诈骗", "贿赂", "泄密", "谣言", "暴力", "色情", "腐败", "重大事故"]


class TemplateNotFound(Exception):
    pass


class MissingElements(Exception):
    def __init__(self, missing: list[str]):
        super().__init__("缺少必填要素")
        self.missing = missing


SYSTEM_GENERATION_PROMPT = (
    "你是一名资深企业公文/新闻撰稿人。根据给定的模板结构、要素与文风要求，撰写一篇完整、合规的中文稿件初稿。\n"
    "必须遵守：\n"
    "1. 严格按模板的 sections 章节结构组织内容，每个 required 章节都要有实质内容，章节顺序一致。\n"
    "2. 所有事实（数据、金额、日期、人名、头衔、机构名、地名）只能来自用户提供的要素或参考素材，禁止编造。\n"
    "3. 用户未提供的必要信息，用「【待补充：…】」占位符标注，不得虚构。\n"
    "4. 输出 Markdown 格式，首行为 '# 标题'。\n"
    "5. 严格遵循给定的文风要求。"
)


def _elements_text(elements: list[dict]) -> str:
    return "\n".join(f"- {e.get('name', '')}: {e.get('value', '')}" for e in elements)


def _resolve_styles(request: dict) -> list[str]:
    """决定本次生成涉及的文风列表：主风格 style + 附加 styles，去重保序。"""
    styles = []
    primary = (request.get("style") or "正式").strip()
    for s in [primary, *(request.get("styles") or [])]:
        if s and s not in styles:
            styles.append(s)
    return styles


def _style_guidelines(style_name: str) -> str:
    styles = load_styles()
    for s in styles.get("styles", []):
        if s.get("name") == style_name or s.get("key") == style_name:
            return s.get("tone_guidelines", "")
    return ""


def load_materials_text(db: Session, refs: list) -> str:
    """按素材 id 读取文本内容，用于生成时注入上下文（全文注入简化方案）。"""
    if not refs:
        return ""
    chunks = []
    for ref in refs:
        material_id = ref
        if isinstance(ref, str) and ref.isdigit():
            material_id = int(ref)
        if isinstance(material_id, int):
            m = db.get(ReferenceMaterial, material_id)
            if m and m.status == "已入库" and m.text_content:
                chunks.append(f"[素材:{m.filename}]\n{m.text_content[:8000]}")
    return "\n\n".join(chunks)


def check_risks(request: dict) -> list[str]:
    """生成前敏感词前置检查，命中返回风险提示列表。"""
    text = (request.get("eventDesc") or "") + " ".join(
        (k.get("value") or "") for k in (request.get("keyFacts") or [])
    )
    return [f"检测到敏感表述：{w}" for w in RISK_WORDS if w in text]


# ===== Mock 实现（无 API Key 时可端到端演示） =====
def mock_generate_content(request: dict, template: dict, elements: list[dict], style: str, materials: str = "") -> str:
    """按模板 sections 骨架 + 要素值拼装 Markdown 演示草稿。"""
    title = (request.get("title") or "").strip() or template.get("title", "未命名")
    lines = [f"# {title}", f"（{style}文风 · 演示草稿，配置 LLM_API_KEY 后切换真实生成）", ""]
    facts = "；".join(f"{k.get('name')}={k.get('value')}" for k in (request.get("keyFacts") or []))
    people = "；".join(f"{p.get('name')}（{p.get('title', '')}）" for p in (request.get("people") or []))
    for sec in template.get("sections", []):
        lines.append(f"## {sec['name']}")
        hint = sec.get("hint", "")
        if sec["key"] == "headline":
            lines.append(f"关于「{request.get('eventDesc', '')}」的{template.get('title', '')}")
        else:
            ctx = []
            if request.get("eventDesc"):
                ctx.append(f"事件：{request['eventDesc']}")
            if facts:
                ctx.append(f"关键要素：{facts}")
            if people:
                ctx.append(f"人物：{people}")
            if materials:
                ctx.append(f"参考素材摘要：{materials[:300]}")
            lines.append(f"（{hint}。{('；'.join(ctx)) or '待补充'}）")
        lines.append("")
    return "\n".join(lines)


def mock_suggest(request: dict, template: dict, main: dict) -> list[str]:
    return ["建议补充竞争定位数据", "导语可更突出核心卖点", f"「{main.get('style', '')}」文风下可加强段落间逻辑衔接"]


# ===== 真实 LLM 调用 =====
def build_generation_messages(request: dict, template: dict, elements: list[dict], style: str, materials: str) -> list[dict]:
    user_payload = {
        "文风": style,
        "文风要求": _style_guidelines(style),
        "模板结构": template,
        "用户输入要素": elements,
        "参考素材": materials or "（无）",
    }
    return [
        {"role": "system", "content": SYSTEM_GENERATION_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def generate_content(request: dict, template: dict, elements: list[dict], style: str, materials: str, llm: LLMClient) -> str:
    if llm.is_mock:
        return mock_generate_content(request, template, elements, style, materials)
    messages = build_generation_messages(request, template, elements, style, materials)
    return llm.chat(messages, model=settings.llm_model_generation, temperature=settings.llm_temperature)


def generate_content_stream(request: dict, template: dict, elements: list[dict], style: str, materials: str, llm: LLMClient):
    """流式生成单文风草稿，逐块 yield 文本（SSE 实时输出用）。Mock 模式一次性 yield 全文。"""
    if llm.is_mock:
        yield mock_generate_content(request, template, elements, style, materials)
        return
    messages = build_generation_messages(request, template, elements, style, materials)
    yield from llm.chat_stream(messages, model=settings.llm_model_generation, temperature=settings.llm_temperature)


def suggest_content(request: dict, template: dict, main: dict, llm: LLMClient) -> list[str]:
    if llm.is_mock:
        return mock_suggest(request, template, main)
    try:
        sys_p = (
            "你是稿件审校专家。针对草稿给出 2-4 条具体的修改建议，每条一句话。"
            '只输出 JSON 数组，如 ["建议1", "建议2"]。'
        )
        user_p = f"模板要求：{template.get('tone_guidelines', '')}\n草稿内容：\n{main.get('content', '')}"
        data = llm.chat_json(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
            model=settings.llm_model_generation,
            temperature=0.3,
        )
        if isinstance(data, list):
            return [str(x) for x in data if x]
        return [str(x) for x in data.get("suggestions", []) if x]
    except (LLMError, ValueError, AttributeError) as exc:
        logger.warning("生成修改建议失败: %s", exc)
        return mock_suggest(request, template, main)


def _extract_title(content: str) -> str:
    for line in content.splitlines():
        if line.strip().startswith("# "):
            return line.strip().lstrip("# ").strip()
    return ""


def persist_draft(db: Session, request: dict, template: Template, state: dict) -> Draft:
    """持久化主风格草稿 + 抽取要素，返回 Draft 记录。"""
    drafts = state.get("drafts") or []
    main_style = (request.get("style") or "正式").strip()
    main = next((d for d in drafts if d.get("style") == main_style), drafts[0] if drafts else {})
    version = 1
    draft_id = f"draft_{uuid.uuid4().hex[:8]}_v{version}"
    draft = Draft(
        id=draft_id,
        title=(request.get("title") or "").strip() or _extract_title(main.get("content", "")),
        template_id=template.id,
        template_name=template.name,
        style=main_style,
        content=main.get("content", ""),
        version=version,
        parent_id=None,
        root_id=draft_id,
        status="草稿",
        model=settings.llm_model_generation,
        created_by=request.get("created_by", ""),
        input_payload=request,
        revision_instruction="",
    )
    db.add(draft)
    for e in state.get("elements") or []:
        db.add(
            DraftElement(
                draft_id=draft_id,
                name=e.get("name", ""),
                value=e.get("value", ""),
                verified_status=e.get("verified_status", "未校验"),
                source_ref=e.get("source_ref", ""),
            )
        )
    for item in state.get("fact_check_report") or []:
        db.add(
            FactCheck(
                draft_id=draft_id,
                claim=item.get("claim", ""),
                status=item.get("status", "无法核实"),
                basis=item.get("basis", ""),
                suggestion=item.get("suggestion", ""),
            )
        )
    db.commit()
    db.refresh(draft)
    return draft
