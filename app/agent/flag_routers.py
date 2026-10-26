"""G5 · 运行时开关管理端点：单点故障时秒级回退，不需要重启与重新发布。

- 读：需要 `agent:audit`（运维可见当前降级状态）
- 写：需要 `agent:admin`（平台管理员权限，网关与 `platform_routers` 口径一致）
- 每次切换写治理审计 `flag.update`；`enabled=null` 表示恢复环境变量默认。
- **边界**：开关状态在进程内，多副本部署需逐副本下发（当前部署为单 worker，见 Dockerfile）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..security import require_internal_token
from . import runtime_flags
from .governance import audit, principal_var

router = APIRouter(dependencies=[Depends(require_internal_token)])


class FlagUpdate(BaseModel):
    enabled: bool | None = Field(default=None, description="null 表示恢复环境变量默认")
    reason: str = Field(default="", max_length=200)


@router.get("/flags")
def list_flags():
    """列出全部开关的当前值、默认值来源与关闭后的回退路径。"""
    principal_var.get().require("agent:audit")
    return {
        "flags": runtime_flags.snapshot(),
        "scope": "in-process",
        "note": "开关状态在进程内；多副本部署需逐副本下发，环境变量仍是默认值口径。",
    }


@router.put("/flags/{name}")
def update_flag(name: str, payload: FlagUpdate, db: Session = Depends(get_db)):
    """热切换一个开关：立即生效，且必须说明原因（写入治理审计）。"""
    principal = principal_var.get()
    principal.require("agent:admin")
    try:
        state = runtime_flags.set_flag(
            name, payload.enabled, operator=principal.user_id, reason=payload.reason,
        )
    except KeyError as exc:
        raise HTTPException(404, detail={"message": f"未知运行时开关：{name}"}) from exc
    audit(
        db, "flag.update", f"flag:{name}",
        details={
            "enabled": state["enabled"], "previous": state["previous"],
            "source": state["source"], "reason": payload.reason[:200],
        },
    )
    db.commit()
    return state