"""G6 · 成本与路由现状查询端点（运维 / 财务口径）。

- 读成本：需 `agent:audit`；跨租户查询额外需 `agent:admin`（平台管理员）。
- 数据来源是落库的 `agent_run.usage`（运行结束时一次性写入），查询本身不触发任何模型调用。
- 成本口径：`cost` 只含已定价模型；`costComplete=false` 时不得当作完整账单（见 `app/services/cost.py`）。

路由现状端点（`GET /model-routing`）回答的是"开关开了没、三层模型配了没"，
避免把"配置了路由"误读成"真的在路由"。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..security import require_internal_token
from ..services import cost, model_router
from .governance import principal_var

router = APIRouter(dependencies=[Depends(require_internal_token)])


@router.get("/costs")
def cost_report(
    db: Session = Depends(get_db),
    days: int = Query(default=7, ge=1, description="统计窗口（天），上限由 COST_QUERY_MAX_DAYS 控制"),
    tenant: str = Query(
        default="",
        description="租户；留空表示当前身份租户，all-tenants 表示全平台（需 agent:admin）",
    ),
    intent: str = Query(default="", description="按业务功能过滤（AgentRun.intent，如 policy_qa）"),
    groupBy: str = Query(
        default="model,purpose,tenant",
        description=f"分组维度，逗号分隔，可选：{','.join(cost.GROUP_DIMENSIONS)}",
    ),
):
    """按租户 / 功能 / 模型聚合成成本报表。"""
    principal = principal_var.get()
    principal.require("agent:audit")
    if days > settings.cost_query_max_days:
        raise HTTPException(422, detail={
            "message": f"days 超过上限 {settings.cost_query_max_days}（COST_QUERY_MAX_DAYS）",
        })

    dims = tuple(dim.strip() for dim in groupBy.split(",") if dim.strip())
    unknown = [dim for dim in dims if dim not in cost.GROUP_DIMENSIONS]
    if unknown:
        raise HTTPException(422, detail={
            "message": f"不支持的 groupBy 维度：{unknown}",
            "allowed": list(cost.GROUP_DIMENSIONS),
        })
    if not dims:
        dims = ("model", "purpose", "tenant")

    requested = (tenant or "").strip()
    all_tenants = requested.lower() in {"all", "all-tenants", "*"}
    if all_tenants:
        # 全平台口径只给平台管理员：普通运维看自己租户，避免成本数据成为跨租户侧信道
        principal.require("agent:admin")
        scope, filter_tenant, display_tenant = "all-tenants", "", "all-tenants"
    else:
        filter_tenant = requested or principal.tenant_id or "default"
        scope, display_tenant = "current-tenant", filter_tenant
        if requested and requested != principal.tenant_id:
            principal.require("agent:admin")
            scope = "cross-tenant"

    until = datetime.now(timezone.utc).replace(tzinfo=None)
    since = until - timedelta(days=days)
    records, truncated = cost.collect_runs(
        db, tenant_id=filter_tenant, since=since, until=until, intent=intent.strip(),
    )
    report = cost.aggregate(records, group_by=dims)
    return {
        "window": {
            "since": since.isoformat(), "until": until.isoformat(), "days": days,
            "tenant": display_tenant, "intent": intent.strip(), "scope": scope,
        },
        "scannedRuns": len(records),
        "truncated": truncated,
        "truncateNote": (
            f"窗口内 AgentRun 超过 COST_QUERY_MAX_RUNS（{settings.cost_query_max_runs}）被截断，"
            "报表只覆盖最近的这些运行，请缩小窗口或提高上限后重算。"
            if truncated else ""
        ),
        **report,
    }


@router.get("/model-routing")
def model_routing_status():
    """模型分层路由现状：开关、阈值、三层模型是否配置（需 agent:audit）。"""
    principal_var.get().require("agent:audit")
    return model_router.snapshot()