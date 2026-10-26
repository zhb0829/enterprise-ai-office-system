"""G9 · LTR 排序模型运维端点。

- 读（`GET /api/agent/ltr`）：需 `agent:audit`，看模式、alpha、门禁阈值、激活模型与历史版本。
- 训练（`POST /api/agent/ltr/train`）：需 `agent:admin`。**训练与指标一律由服务端计算**，
  不接受调用方自报 weights / cv_auc —— 否则"门禁"会退化成"填表"。
  请求体给的是标注样本（features + label，可选 groups = case id 用于按查询分组切折）。
- 激活（`POST /api/agent/ltr/models/{version}/activate`）：需 `agent:admin`，必须先过 `should_promote` 门禁；
  `force` 只允许回滚**曾激活过**的版本，且写进审计。
- 退役（`.../retire`）：需 `agent:admin`。

模型落库后默认是 `shadow`：先看影子排序，再决定是否激活。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..security import require_internal_token
from . import ltr as ranking
from .governance import audit, principal_var

router = APIRouter(dependencies=[Depends(require_internal_token)])

MAX_TRAINING_SAMPLES = 20000


class SamplePayload(BaseModel):
    features: dict[str, float] = Field(default_factory=dict)
    label: int = Field(ge=0, le=1)


class TrainingRequest(BaseModel):
    samples: list[SamplePayload] = Field(min_length=1, max_length=MAX_TRAINING_SAMPLES)
    groups: list[str] = Field(default_factory=list, max_length=MAX_TRAINING_SAMPLES,
                              description="与 samples 等长的分组键（case id）：按查询分组切折，避免自己考自己")
    datasetDigest: str = Field(default="", max_length=64)
    notes: str = Field(default="", max_length=500)
    activate: bool = Field(default=False, description="训练后尝试激活（仍要过门禁）")


class ModelAction(BaseModel):
    reason: str = Field(default="", max_length=200)
    force: bool = Field(default=False, description="仅允许回滚曾激活过的版本；会写进审计")


@router.get("/ltr")
def ltr_status(db: Session = Depends(get_db)) -> dict:
    principal_var.get().require("agent:audit")
    return ranking.snapshot(db)


@router.post("/ltr/train", status_code=201)
def train_ranking_model(payload: TrainingRequest, db: Session = Depends(get_db)) -> dict:
    """服务端训练一个排序模型并落 shadow；指标全部由服务端计算。"""
    principal = principal_var.get()
    principal.require("agent:admin")
    samples = [
        ranking.TrainingSample(
            features={name: float(item.features.get(name, 0.0)) for name in ranking.FEATURE_NAMES},
            label=int(item.label),
        )
        for item in payload.samples
    ]
    groups = payload.groups or None
    try:
        model = ranking.train_model(samples, dataset_digest=payload.datasetDigest, groups=groups)
    except ValueError as exc:
        raise HTTPException(422, detail={"message": str(exc)}) from exc
    row = ranking.save_model(db, model, status="shadow", notes=payload.notes)
    gate = ranking.should_promote(model)
    result = {
        "version": row.id, "status": row.status, "metrics": model.metrics,
        "weights": model.weights, "bias": model.bias, "positives": model.positives,
        "gate": gate,
        "note": (
            "训练与指标由服务端计算（foldUnit=" + str(model.metrics.get("foldUnit")) + "）；"
            "模型先落 shadow，激活要另行调用并再次过门禁。"
        ),
    }
    audit(db, "ltr.train", f"ranking-model:{row.id}", details={
        "samples": model.samples, "positives": model.positives,
        "cvAuc": model.metrics.get("cv_auc"), "foldUnit": model.metrics.get("foldUnit"),
        "datasetDigest": payload.datasetDigest, "gate": gate["promoted"],
    })
    if payload.activate and gate["promoted"]:
        result.update(ranking.activate_model(db, row.id, operator=principal.user_id))
    result["status"] = row.status
    db.commit()
    return result


@router.post("/ltr/models/{version}/activate")
def activate_model(version: str, payload: ModelAction, db: Session = Depends(get_db)) -> dict:
    principal = principal_var.get()
    principal.require("agent:admin")
    try:
        result = ranking.activate_model(
            db, version, operator=principal.user_id, force=payload.force,
        )
    except HTTPException:
        db.rollback()
        raise
    db.commit()
    return {**result, "reason": payload.reason}


@router.post("/ltr/models/{version}/retire")
def retire_model(version: str, payload: ModelAction, db: Session = Depends(get_db)) -> dict:
    principal = principal_var.get()
    principal.require("agent:admin")
    result = ranking.retire_model(db, version, operator=principal.user_id)
    db.commit()
    return {**result, "reason": payload.reason}