"""多轮修改与回退服务：修订生成、差异说明、版本持久化、版本树构建。

版本历史采用 draft.parent_id + root_id 版本树（MVP 实现，LangGraph checkpoint 后续再接）。
"""
import logging
import uuid

from sqlalchemy.orm import Session

from ..config import settings
from ..models import Draft, DraftElement, FactCheck
from ..schemas import VersionNode
from .llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

REVISE_SYSTEM_PROMPT = (
    "你是一名资深企业文稿审校修订专家。根据用户的修改指令修改给定的稿件。\n"
    "必须遵守：\n"
    "1. 只按指令修改对应内容，未涉及的段落保持原样，整体 Markdown 章节结构不变。\n"
    "2. 不得引入用户要素或参考素材之外的任何新事实（数据、人名、日期、机构、地名）。\n"
    "3. 输出修订后的完整全文，Markdown 格式，首行为 '# 标题'。"
)

DIFF_SYSTEM_PROMPT = (
    "对比给定的原稿与修订稿，输出 2-4 条本次修改的差异说明，每条一句话。"
    '只输出 JSON 数组，如 ["修改了……", "补充了……"]。'
)


def mock_revise(content: str, instruction: str) -> str:
    return content + f"\n\n---\n\n（修订：按指令「{instruction}」生成。配置 LLM_API_KEY 后切换真实修订。）\n"


def revise_content(base: Draft, instruction: str, llm: LLMClient, materials: str = "") -> str:
    """按修改指令生成修订稿全文。"""
    if llm.is_mock:
        return mock_revise(base.content, instruction)
    messages = [
        {"role": "system", "content": REVISE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"原稿：\n{base.content}\n\n参考素材：\n{materials or '（无）'}\n\n修改指令：{instruction}",
        },
    ]
    return llm.chat(messages, model=settings.llm_model_generation, temperature=0.3)


def diff_summary(base: Draft, new_content: str, instruction: str, llm: LLMClient) -> list[str]:
    """生成本次修改的差异说明列表。"""
    if llm.is_mock:
        return [f"已按指令执行修改：{instruction}"]
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": DIFF_SYSTEM_PROMPT},
                {"role": "user", "content": f"原稿：\n{base.content}\n\n修订稿：\n{new_content}"},
            ],
            model=settings.llm_model_generation,
            temperature=0.1,
        )
        if isinstance(data, list):
            return [str(x) for x in data if x]
        return [str(x) for x in data.get("changes", []) if x]
    except (LLMError, ValueError, AttributeError) as exc:
        logger.warning("生成差异说明失败: %s", exc)
        return [f"已按指令执行修改：{instruction}"]


def next_version_number(db: Session, root_id: str) -> int:
    row = (
        db.query(Draft.version)
        .filter(Draft.root_id == root_id)
        .order_by(Draft.version.desc())
        .first()
    )
    return (row[0] + 1) if row else 1


def persist_revision(
    db: Session,
    base: Draft,
    new_content: str,
    instruction: str,
    diff: list[str],
    fact_check_report: list[dict] | None = None,
) -> Draft:
    """基于 base 草稿创建新版本，返回新 Draft 记录。"""
    version = next_version_number(db, base.root_id or base.id)
    draft_id = f"draft_{uuid.uuid4().hex[:8]}_v{version}"
    draft = Draft(
        id=draft_id,
        title=base.title,
        template_id=base.template_id,
        template_name=base.template_name,
        style=base.style,
        content=new_content,
        version=version,
        parent_id=base.id,
        root_id=base.root_id or base.id,
        status="草稿",
        model=settings.llm_model_generation,
        created_by=base.created_by,
        input_payload=base.input_payload,
        revision_instruction=instruction,
    )
    db.add(draft)
    for e in base.elements:
        db.add(
            DraftElement(
                draft_id=draft_id,
                name=e.name,
                value=e.value,
                verified_status=e.verified_status,
                source_ref=e.source_ref,
            )
        )
    for item in fact_check_report or []:
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


def build_version_tree(db: Session, draft: Draft) -> VersionNode:
    """以版本树根为根构建整棵树（含所有分支），用于 GET /versions。"""
    root_id = draft.root_id or draft.id
    nodes = db.query(Draft).filter(Draft.root_id == root_id).all()
    by_parent: dict[str | None, list[Draft]] = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)
    for kids in by_parent.values():
        kids.sort(key=lambda n: n.created_at)

    def build(node_id: str) -> VersionNode:
        node = next(n for n in nodes if n.id == node_id)
        return VersionNode(
            id=node.id,
            version=node.version,
            parent_id=node.parent_id,
            title=node.title,
            status=node.status,
            revision_instruction=node.revision_instruction,
            created_at=node.created_at,
            children=[build(k.id) for k in by_parent.get(node.id, [])],
        )

    return build(root_id)
