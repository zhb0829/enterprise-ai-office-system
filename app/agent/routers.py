from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import false, or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..observability import user_id_var
from ..security import require_internal_token
from .models import AgentRun
from .registry import ToolError, registry
from .runtime import agent_run
from .tools import SKILLS
from .governance import DataLevel, principal_var

router = APIRouter(dependencies=[Depends(require_internal_token)])


class ToolCall(BaseModel):
    input: dict = Field(default_factory=dict)
    idempotencyKey: str = Field(default="", max_length=128)


@router.get("/registry")
def tool_registry():
    # 工具清单与入参 Schema 属治理信息：要求受信身份 + 只读权限，不再"有内部令牌就能看"。
    principal_var.get().require("policy:read")
    return {"tools": registry.list(), "skills": SKILLS}


@router.post("/tools/{name}/invoke")
@agent_run("tool_invocation")
def invoke_tool(name: str, payload: ToolCall, request: Request, db: Session = Depends(get_db)):
    # G7：工具判权必须用**角色收敛后**的权限，不能回读原始请求头——
    # 否则"声明 member + 伪造全量权限头"的请求能借工具绕过角色基线。
    identity = principal_var.get()
    if not identity.authenticated:
        raise HTTPException(403, "trusted user identity required")
    permissions = set(identity.permissions)
    principal = identity.user_id
    try:
        return {"output": registry.invoke(name, payload.input, permissions=permissions, principal=principal, idempotency_key=payload.idempotencyKey)}
    except ToolError as exc:
        status = {"FORBIDDEN": 403, "TOOL_NOT_FOUND": 404, "INVALID_INPUT": 422, "TOOL_TIMEOUT": 504, "CAPACITY_EXCEEDED": 429, "IDEMPOTENCY_CONFLICT": 409, "IN_PROGRESS": 409}.get(exc.code, 502)
        raise HTTPException(status, {"code": exc.code, "message": str(exc)}) from exc


@router.get("/runs")
def list_runs(request: Request, limit: int = 20, db: Session = Depends(get_db)):
    p = principal_var.get()
    p.require("agent:audit")
    criteria = false() if p.public_only else (
        (AgentRun.tenant_id == p.tenant_id)
        & AgentRun.classification.in_([level.name for level in DataLevel if level <= p.clearance])
        & or_(AgentRun.department_id == "", AgentRun.department_id == p.department_id)
    )
    rows = db.query(AgentRun).filter(criteria).order_by(AgentRun.started_at.desc()).limit(max(1, min(limit, 100))).all()
    return [{"runId": row.run_id, "traceId": row.trace_id, "intent": row.intent, "status": row.status, "latencyMs": row.latency_ms, "startedAt": row.started_at} for row in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: str, request: Request, db: Session = Depends(get_db)):
    p = principal_var.get()
    if not p.authenticated:
        raise HTTPException(403, "trusted user identity required")
    row = db.get(AgentRun, run_id)
    if not row:
        raise HTTPException(404, "run not found")
    if row.tenant_id != p.tenant_id or not p.can_read(row.classification, row.tenant_id, row.department_id):
        raise HTTPException(404, "run not found")
    if "agent:audit" not in p.permissions and (not row.user_id or row.user_id != p.user_id):
        raise HTTPException(403, "run access denied")
    return jsonable_encoder({column.name: getattr(row, column.name) for column in AgentRun.__table__.columns})
