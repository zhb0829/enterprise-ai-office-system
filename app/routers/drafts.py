"""草稿生成/修改/润色/导出接口。"""
import json
import hmac
import logging
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Draft, FactCheck, Template
from ..agent.models import DraftEvidence, DraftReview
from ..agent.review import assert_publishable, evidence_rows, persist_evidence, require_reviewer, review_draft, review_out
from ..agent.runtime import agent_run, agent_stream, context_call, current_run, step
from ..agent.roles import AgentPipeline, EvidenceVerifier, FunctionActor, FunctionRetriever, TaskContext, WorkflowPlanner
from ..agent.governance import governed_get
from ..observability import user_id_var
from ..security import require_internal_token
from ..schemas import (
    DraftDetail,
    EditRequest,
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
    StatusUpdateRequest,
    VersionNode,
    ReviewRequest,
)
from ..services import generation, model_router
from ..services.generation import MissingElements, TemplateNotFound
from ..services.llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

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


def _material_query(request: dict) -> str:
    facts = " ".join(f"{x.get('name', '')} {x.get('value', '')}" for x in request.get("keyFacts") or [])
    people = " ".join(f"{x.get('name', '')} {x.get('title', '')}" for x in request.get("people") or [])
    return " ".join([request.get("title") or "", request.get("eventDesc") or "", facts, people]).strip()


def _to_draft_detail(draft: Draft, db: Session | None = None) -> DraftDetail:
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
        evidence=[
            {"id": item.id, "claim": item.claim, "status": item.status, "sources": item.sources, "contentHash": item.content_hash}
            for item in evidence_rows(db, draft.id)
        ] if db else [],
        reviews=[review_out(item) for item in db.query(DraftReview).filter(DraftReview.draft_id == draft.id).order_by(DraftReview.id).all()] if db else [],
    )


@router.post("/news", response_model=GenerateResponse)
@agent_run("announcement", plan=("validate", "materials", "extract", "generate", "verify", "persist"))
def generate_news(payload: GenerateRequest, db: Session = Depends(get_db)):
    """初稿生成：要素 + 模板 + 文风 → 草稿 + 建议 + 多文风版本。

    缺必填要素时返回 422，body.detail.missing 为缺失清单。
    """
    request = payload.model_dump()
    request["created_by"] = user_id_var.get()
    llm = LLMClient()
    from ..graphs.drafting import build_draft_graph

    def retrieve(context):
        template = _get_template(db, request["template"])
        materials = generation.load_materials_text(db, request.get("referenceMaterials") or [], _material_query(request))
        schema = template.schema_
        db.expunge(template)
        db.rollback()
        return {"template": template, "schema": schema, "materials": materials}

    def act(context, evidence):
        state = build_draft_graph(llm).invoke({
            "request": request, "template": evidence["schema"], "materials": evidence["materials"],
        })
        return {"state": state, "template": evidence["template"]}

    def verify(context, evidence, result):
        state = result["state"]
        if state.get("missing"):
            raise HTTPException(422, detail={"message": "缺少必填要素，请补充后重新提交", "missing": state["missing"]})
        return {
            "passed": any(d.get("content") and not d.get("error") for d in state.get("drafts", [])),
            "fact_checks": state.get("fact_check_report", []), "human_review_required": True,
        }

    bundle = AgentPipeline(
        WorkflowPlanner(permission="draft:write"),
        FunctionRetriever(retrieve), FunctionActor(act), EvidenceVerifier(verify),
    ).execute(TaskContext("announcement", request, memory=current_run.get().memory))
    state, template = bundle["state"], bundle["template"]

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
        sources=[source for item in fact_report for source in item.get("evidence", [])],
        generatedAt=draft.created_at,
        model=draft.model,
        riskFlags=risk_flags,
        variants=state.get("drafts") or [],
        runId=current_run.get().run_id,
    )


@router.post("/news/stream")
def generate_news_stream(payload: GenerateRequest, db: Session = Depends(get_db)):
    """初稿生成（SSE 流式）：要素抽取 → 主文风正文逐块输出 → 其他文风并行 → 核查/建议 → 完整结果。

    事件类型：status / delta / done / error。
    """
    from ..services import extraction, factcheck
    from ..services.generation import (
        _resolve_styles,
        check_risks,
        generate_content_stream,
        persist_draft,
        suggest_content,
    )

    request = payload.model_dump()
    request["created_by"] = user_id_var.get()
    llm = LLMClient()

    def retrieve(context):
        template = _get_template(db, request["template"])
        materials = generation.load_materials_text(db, request.get("referenceMaterials") or [], _material_query(request))
        schema = template.schema_
        db.expunge(template)
        db.rollback()
        return {"template": template, "schema": schema, "materials": materials}

    def _sse(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    @agent_stream("announcement_stream", db, payload)
    def event_stream():
        try:
            context = TaskContext("announcement_stream", request, memory=current_run.get().memory)
            planner = WorkflowPlanner(permission="draft:write")
            with step("planner") as record:
                plan = planner.plan(context)
                current_run.get().plan = list(plan.stages)
                record["output"] = {"stages": list(plan.stages)}
            with step("retriever") as record:
                evidence = FunctionRetriever(retrieve).retrieve(context, plan)
                record["output"] = evidence
            template, template_schema, materials = evidence["template"], evidence["schema"], evidence["materials"]
            missing = extraction.validate_required(request, template_schema)
            if missing:
                yield _sse(
                    {
                        "type": "error",
                        "detail": {"message": "缺少必填要素，请补充后重新提交", "missing": missing},
                    }
                )
                return

            yield _sse({"type": "status", "stage": "extract"})
            elements = extraction.extract_elements(request, template_schema, llm)

            styles = _resolve_styles(request)
            main_style = styles[0]
            yield _sse({"type": "status", "stage": "generate", "style": main_style})

            main_parts: list[str] = []
            with step("actor") as record:
                stream = FunctionActor(lambda context, evidence: {
                    "stream": generate_content_stream(request, template_schema, elements, main_style, materials, llm),
                }).act(context, plan, evidence)["stream"]
                for chunk in stream:
                    main_parts.append(chunk)
                    yield _sse({"type": "delta", "text": chunk})
                record["output"] = {"content": "".join(main_parts)}
            main_content = "".join(main_parts)

            other_drafts: list[dict] = []
            if len(styles) > 1:

                def _gen(style: str) -> dict:
                    try:
                        content = generation.generate_content(request, template_schema, elements, style, materials, llm)
                        return {"style": style, "content": content}
                    except Exception as exc:  # noqa: BLE001
                        logger.error("其他文风生成失败 [%s]: %s", style, exc)
                        return {"style": style, "content": "", "error": str(exc)}

                with ThreadPoolExecutor(max_workers=min(len(styles) - 1, 4)) as ex:
                    other_drafts = [future.result() for future in [ex.submit(context_call(_gen, style)) for style in styles[1:]]]

            drafts = [{"style": main_style, "content": main_content}] + other_drafts

            yield _sse({"type": "status", "stage": "factcheck"})
            fact_report = factcheck.run_factcheck(main_content, elements, materials, llm)

            yield _sse({"type": "status", "stage": "suggest"})
            suggestions = suggest_content(
                request, template_schema, {"style": main_style, "content": main_content}, llm
            )
            risk_flags = list(check_risks(request))
            unverifiable = [r for r in fact_report if r.get("status") == "无法核实"]
            if unverifiable:
                risk_flags.append(f"存在 {len(unverifiable)} 项无法核实的事实，发布前需人工确认")

            state = {
                "drafts": drafts,
                "elements": elements,
                "fact_check_report": fact_report,
                "suggestions": suggestions,
                "risk_flags": risk_flags,
            }
            with step("verifier") as record:
                report = EvidenceVerifier(lambda context, evidence, result: {
                    "passed": bool(result["content"].strip()), "fact_checks": fact_report,
                    "human_review_required": True,
                }).verify(context, plan, evidence, {"content": main_content})
                current_run.get().verification.update(report)
                record["output"] = report
            try:
                draft = persist_draft(db, request, template, state)
            except LLMError as exc:
                yield _sse({"type": "error", "detail": {"message": "LLM 调用失败", "error": str(exc)}})
                return

            yield _sse(
                {
                    "type": "done",
                    "draft": draft.content,
                    "revisionSuggestions": suggestions,
                    "factCheckReport": fact_report,
                    "versionId": draft.id,
                    "sources": [source for item in fact_report for source in item.get("evidence", [])],
                    "runId": current_run.get().run_id,
                    "generatedAt": draft.created_at.isoformat(),
                    "model": draft.model,
                    "riskFlags": risk_flags,
                    "variants": [{"style": d.get("style"), "content": d.get("content", "")} for d in drafts],
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("流式生成失败")
            yield _sse({"type": "error", "detail": {"message": "生成失败", "error": str(exc)}})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/revise", response_model=ReviseResponse)
@agent_run("announcement_revision")
def revise(payload: ReviseRequest, db: Session = Depends(get_db)):
    """多轮修改：携带修改指令基于原版本生成新版本，返回新草稿 + 差异说明。"""
    base = governed_get(db, Draft, payload.draftId)
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
    base_request = base.input_payload or {}
    materials = generation.load_materials_text(
        db, base_request.get("referenceMaterials") or [], _material_query(base_request)
    )
    db.expunge_all()
    db.rollback()
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
        base = governed_get(db, Draft, payload.draftId)
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
        model=(model_router.last_decision("draft.polish") or {}).get("model") or settings.llm_model_generation,
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
        download_url=f"/api/files/export/{urllib.parse.quote(filename)}",
        format=payload.format,
    )


@router.get("/{draft_id}/versions", response_model=VersionNode)
def get_version_tree(draft_id: str, db: Session = Depends(get_db)):
    """版本历史（树状），返回整棵版本树（根节点展开）。"""
    draft = governed_get(db, Draft, draft_id)
    if not draft:
        raise HTTPException(404, "草稿不存在")
    from ..services.revise import build_version_tree

    return build_version_tree(db, draft)


@router.get("/{draft_id}/factcheck", response_model=list[FactCheckItem])
def get_factcheck_report(draft_id: str, db: Session = Depends(get_db)):
    """独立查询核查报告，供发布前复核与历史查看。"""
    draft = governed_get(db, Draft, draft_id)
    if not draft:
        raise HTTPException(404, "草稿不存在")
    return [
        FactCheckItem(claim=fc.claim, status=fc.status, basis=fc.basis, suggestion=fc.suggestion)
        for fc in draft.fact_checks
    ]


@router.post("/{draft_id}/status", response_model=DraftDetail)
def update_draft_status(draft_id: str, payload: StatusUpdateRequest, request: Request, db: Session = Depends(get_db)):
    """状态流转：草稿/审阅/发布。发布前存在不一致或无法核实时阻断。"""
    draft = governed_get(db, Draft, draft_id)
    if not draft:
        raise HTTPException(404, "草稿不存在")

    transitions = {
        "草稿": {"审阅"},
        "审阅": {"草稿", "发布"},
        "发布": set(),
    }
    current = draft.status if draft.status in transitions else "草稿"
    target = payload.status
    if target == current:
        return _to_draft_detail(draft, db)
    if target not in transitions[current]:
        raise HTTPException(422, detail={"message": f"不允许从「{current}」流转到「{target}」"})
    if target == "发布":
        supplied_token = request.headers.get("x-internal-token", "")
        if (
            not settings.ai_internal_token
            or not hmac.compare_digest(supplied_token, settings.ai_internal_token)
            or not user_id_var.get()
            or "draft:write" not in request.headers.get("x-user-permissions", "").split(",")
        ):
            raise HTTPException(403, "trusted identity and draft:write permission required for publication")
        assert_publishable(db, draft)

    draft.status = target
    db.commit()
    db.refresh(draft)
    return _to_draft_detail(draft, db)


@router.post("/{draft_id}/review")
def submit_review(draft_id: str, payload: ReviewRequest, reviewer: str = Depends(require_reviewer), db: Session = Depends(get_db)):
    draft = governed_get(db, Draft, draft_id)
    if not draft:
        raise HTTPException(404, "草稿不存在")
    return review_out(review_draft(db, draft, reviewer, payload.decision, payload.comment))


@router.get("", dependencies=[Depends(require_reviewer)])
def list_drafts(status: str = "审阅", limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    query = db.query(Draft)
    if status:
        query = query.filter(Draft.status == status)
    total = query.count()
    rows = query.order_by(Draft.created_at.desc(), Draft.id).offset(offset).limit(limit).all()
    return {"total": total, "items": [{
        "id": row.id, "title": row.title, "version": row.version, "status": row.status,
        "createdBy": row.created_by, "createdAt": row.created_at,
    } for row in rows]}


@router.post("/{draft_id}/verify", dependencies=[Depends(require_internal_token)])
@agent_run("announcement_reverification")
def verify_draft(draft_id: str, request: Request, db: Session = Depends(get_db)):
    permissions = request.headers.get("x-user-permissions", "").split(",")
    if not user_id_var.get() or "draft:verify" not in permissions:
        raise HTTPException(403, "trusted identity and draft:verify permission required")
    draft = governed_get(db, Draft, draft_id)
    if not draft:
        raise HTTPException(404, "草稿不存在")
    if draft.status == "发布":
        raise HTTPException(422, "已发布版本不能重新核查，请先创建新版本")
    if not draft.created_by:
        draft.created_by = user_id_var.get()
    from ..services.factcheck import run_factcheck
    elements = [{"name": e.name, "value": e.value, "source_ref": e.source_ref, "verified_status": e.verified_status} for e in draft.elements]
    payload = draft.input_payload or {}
    materials = generation.load_materials_text(db, payload.get("referenceMaterials") or [], _material_query(payload))
    report = run_factcheck(draft.content, elements, materials, LLMClient())
    # An unchanged fingerprint must not resurrect an approval after re-verification.
    db.add(DraftReview(
        draft_id=draft.id, reviewer_id=user_id_var.get(), decision="invalidated",
        comment="重新核查事实，原审批失效", content_hash="", evidence_hash="",
    ))
    db.query(DraftEvidence).filter(DraftEvidence.draft_id == draft.id).delete(synchronize_session=False)
    draft.fact_checks = [FactCheck(claim=r["claim"], status=r["status"], basis=r.get("basis", ""), suggestion=r.get("suggestion", "")) for r in report]
    persist_evidence(db, draft, report)
    db.commit()
    db.refresh(draft)
    return _to_draft_detail(draft, db)

@router.post("/{draft_id}/revert", response_model=ReviseResponse)
def revert(draft_id: str, payload: RevertRequest, db: Session = Depends(get_db)):
    """回退：基于当前版本生成一个新版本，其内容等于目标历史版本。"""
    base = governed_get(db, Draft, draft_id)
    if not base:
        raise HTTPException(404, "草稿不存在")
    target = governed_get(db, Draft, payload.targetId)
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


@router.post("/{draft_id}/edit", response_model=ReviseResponse)
def edit_draft_content(draft_id: str, payload: EditRequest, db: Session = Depends(get_db)):
    """手动编辑正文：基于当前草稿生成新版本并落库（不经过 LLM）。"""
    base = governed_get(db, Draft, draft_id)
    if not base:
        raise HTTPException(404, "草稿不存在")
    content = payload.content.strip()
    if not content:
        raise HTTPException(422, detail={"message": "正文不能为空"})

    from ..services.revise import persist_revision

    new_draft = persist_revision(db, base, content, "手动编辑正文", ["已手动编辑正文"])
    return ReviseResponse(
        draft=new_draft.content,
        versionId=new_draft.id,
        version=new_draft.version,
        diffSummary=["已手动编辑正文"],
        generatedAt=new_draft.created_at,
        model=new_draft.model,
    )


@router.get("/{draft_id}", response_model=DraftDetail)
def get_draft(draft_id: str, db: Session = Depends(get_db)):
    """草稿详情（含抽取要素与事实核查结果）。"""
    draft = governed_get(db, Draft, draft_id)
    if not draft:
        raise HTTPException(404, "草稿不存在")
    return _to_draft_detail(draft, db)
