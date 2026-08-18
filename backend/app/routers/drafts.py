"""草稿生成/修改/润色/导出接口。"""
import urllib.parse
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Draft, Template
from ..schemas import (
    DraftDetail,
    ElementOut,
    ExportRequest,
    ExportResponse,
    FactCheckItem,
    GenerateRequest,
    GenerateResponse,
    PolishChange,
    PolishRequest,
    PolishResponse,
    RevertRequest,
    ReviseRequest,
    ReviseResponse,
    VersionNode,
)
from ..services import generation
from ..services.generation import MissingElements, TemplateNotFound
from ..services.llm import LLMClient, LLMError

router = APIRouter()


def _get_template(db: Session, name: str) -> Template:
    tpl = (
        db.query(Template)
        .filter(Template.name == name, Template.is_active.is_(True))
        .first()
    )
    if not tpl:
        raise HTTPException(404, f"模板不存在或已停用: {name}")
    return tpl


@router.post("/news", response_model=GenerateResponse)
def generate_news(payload: GenerateRequest, db: Session = Depends(get_db)):
    """初稿生成：要素 + 模板 + 文风 → 草稿 + 建议 + 多文风版本。

    缺必填要素时返回 422，body.detail.missing 为缺失清单。
    """
    request = payload.model_dump()
    template = _get_template(db, request["template"])
    llm = LLMClient()
    materials = generation.load_materials_text(db, request.get("referenceMaterials") or [])

    from ..graphs.drafting import build_draft_graph

    graph = build_draft_graph(llm)
    state = graph.invoke(
        {
            "request": request,
            "template": template.schema_,
            "materials": materials,
        }
    )

    missing = state.get("missing") or []
    if missing:
        raise HTTPException(
            422,
            detail={"message": "缺少必填要素，请补充后重新提交", "missing": missing},
        )

    try:
        draft = generation.persist_draft(db, request, template, state)
    except LLMError as exc:
        raise HTTPException(502, detail={"message": "LLM 调用失败", "error": str(exc)})

    fact_report = state.get("fact_check_report") or []
    risk_flags = list(state.get("risk_flags") or [])
    unverifiable = [r for r in fact_report if r.get("status") == "无法核实"]
    if unverifiable:
        risk_flags.append(f"存在 {len(unverifiable)} 项无法核实的事实，发布前需人工确认")

    return GenerateResponse(
        draft=draft.content,
        revisionSuggestions=state.get("suggestions") or [],
        factCheckReport=fact_report,
        versionId=draft.id,
        sources=[],
        generatedAt=draft.created_at,
        model=draft.model,
        riskFlags=risk_flags,
        variants=state.get("drafts") or [],
    )


@router.post("/revise", response_model=ReviseResponse)
def revise(payload: ReviseRequest, db: Session = Depends(get_db)):
    """多轮修改：携带修改指令基于原版本生成新版本，返回新草稿 + 差异说明。"""
    base = db.get(Draft, payload.draftId)
    if not base:
        raise HTTPException(404, "草稿不存在")
    instruction = payload.instruction.strip()
    if not instruction:
        raise HTTPException(422, detail={"message": "修改指令不能为空"})

    llm = LLMClient()
    from ..graphs.drafting import build_revision_graph

    elements = [
        {"name": e.name, "value": e.value, "source_ref": e.source_ref, "verified_status": e.verified_status}
        for e in base.elements
    ]
    materials = generation.load_materials_text(
        db, (base.input_payload or {}).get("referenceMaterials") or []
    )
    graph = build_revision_graph(llm)
    state = graph.invoke(
        {"base": base, "instruction": instruction, "elements": elements, "materials": materials}
    )

    try:
        from ..services.revise import persist_revision

        new_draft = persist_revision(
            db,
            base,
            state["new_content"],
            instruction,
            state.get("diff") or [],
            state.get("fact_check_report") or [],
        )
    except LLMError as exc:
        raise HTTPException(502, detail={"message": "LLM 调用失败", "error": str(exc)})

    return ReviseResponse(
        draft=new_draft.content,
        versionId=new_draft.id,
        version=new_draft.version,
        diffSummary=state.get("diff") or [],
        generatedAt=new_draft.created_at,
        model=new_draft.model,
    )


@router.post("/polish", response_model=PolishResponse)
def polish(payload: PolishRequest, db: Session = Depends(get_db)):
    """润色：输入系统草稿（draftId）或用户粘贴的外部草稿（text），输出润色稿 + 逐条修改说明。

    draftId 模式：润色结果作为新版本落库（并入版本树）；text 模式：不落库，versionId 为 null。
    """
    if not payload.text and not payload.draftId:
        raise HTTPException(422, detail={"message": "draftId 与 text 至少提供一个"})
    if payload.text and payload.draftId:
        raise HTTPException(422, detail={"message": "draftId 与 text 只能二选一"})

    llm = LLMClient()
    from ..services.polish import polish_text

    if payload.draftId:
        base = db.get(Draft, payload.draftId)
        if not base:
            raise HTTPException(404, "草稿不存在")
        text = base.content
    else:
        base = None
        text = payload.text or ""

    polished, changes = polish_text(text, llm)

    version_id = None
    if base is not None:
        try:
            from ..services.revise import persist_revision

            reasons = [c["reason"] for c in changes] or ["已完成润色"]
            new_draft = persist_revision(db, base, polished, "润色", reasons)
            version_id = new_draft.id
        except LLMError as exc:
            raise HTTPException(502, detail={"message": "LLM 调用失败", "error": str(exc)})

    return PolishResponse(
        polished=polished,
        changes=[PolishChange(**c) for c in changes],
        versionId=version_id,
        generatedAt=datetime.now(timezone.utc),
        model=settings.llm_model_generation,
    )


@router.post("/export", response_model=ExportResponse)
def export(payload: ExportRequest, db: Session = Depends(get_db)):
    """导出草稿为 Markdown / DOCX。PDF 需 pandoc + 中文字体，MVP 暂不支持。"""
    from ..services.export import UnsupportedExportFormat, export_draft

    try:
        path, filename = export_draft(db, payload.draftId, payload.format)
    except FileNotFoundError:
        raise HTTPException(404, "草稿不存在")
    except UnsupportedExportFormat as e:
        raise HTTPException(501, detail={"message": str(e)})

    return ExportResponse(
        file_path=path,
        download_url=f"/static/exports/{urllib.parse.quote(filename)}",
        format=payload.format,
    )


@router.get("/{draft_id}/versions", response_model=VersionNode)
def get_version_tree(draft_id: str, db: Session = Depends(get_db)):
    """版本历史（树状），返回整棵版本树（根节点展开）。"""
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "草稿不存在")
    from ..services.revise import build_version_tree

    return build_version_tree(db, draft)


@router.post("/{draft_id}/revert", response_model=ReviseResponse)
def revert(draft_id: str, payload: RevertRequest, db: Session = Depends(get_db)):
    """回退：基于当前版本生成一个新版本，其内容等于目标历史版本。"""
    base = db.get(Draft, draft_id)
    if not base:
        raise HTTPException(404, "草稿不存在")
    target = db.get(Draft, payload.targetId)
    if not target:
        raise HTTPException(404, "目标版本不存在")
    if (target.root_id or target.id) != (base.root_id or base.id):
        raise HTTPException(422, detail={"message": "目标版本与当前草稿不属于同一版本树"})

    instruction = f"回退至版本 {target.id}（v{target.version}）"
    from ..services.revise import persist_revision

    new_draft = persist_revision(
        db,
        base,
        target.content,
        instruction,
        [f"已回退至版本 v{target.version}（{target.id}）"],
    )
    return ReviseResponse(
        draft=new_draft.content,
        versionId=new_draft.id,
        version=new_draft.version,
        diffSummary=[f"已回退至版本 v{target.version}（{target.id}）"],
        generatedAt=new_draft.created_at,
        model=new_draft.model,
    )


@router.get("/{draft_id}", response_model=DraftDetail)
def get_draft(draft_id: str, db: Session = Depends(get_db)):
    """草稿详情（含抽取要素与事实核查结果）。"""
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "草稿不存在")
    return DraftDetail(
        id=draft.id,
        title=draft.title,
        template_name=draft.template_name,
        style=draft.style,
        content=draft.content,
        version=draft.version,
        parent_id=draft.parent_id,
        root_id=draft.root_id,
        status=draft.status,
        model=draft.model,
        revision_instruction=draft.revision_instruction,
        input_payload=draft.input_payload,
        created_at=draft.created_at,
        elements=[ElementOut.model_validate(e) for e in draft.elements],
        fact_checks=[
            FactCheckItem(claim=fc.claim, status=fc.status, basis=fc.basis, suggestion=fc.suggestion)
            for fc in draft.fact_checks
        ],
    )