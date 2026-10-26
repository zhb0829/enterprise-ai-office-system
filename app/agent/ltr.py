"""G9 · LTR 学习排序演进：**RRF 保底，LTR 渐进替换**。

纪律（与项目既有克制口径一致）
------------------------------

- **RRF 保底**：`off` 模式、模型缺失、任何异常都退回 RRF 顺序；LTR 只可能在候选池内重新排序，
  绝不允许因为模型出问题让检索失败、返回空或丢掉 RRF 分。
- **渐进替换**：三档模式 `off` → `shadow`（只算分、记录影子排序，不改线上顺序）→
  `blend`（`(1-alpha)·RRF + alpha·LTR`）。alpha 由 `LTR_BLEND_ALPHA` 控制；生产做法是小步提高、
  每一档都要有 `evals.ltr_compare` 的**样本外**增益作依据，不做"一步到位 replace"。
- **特征只用能解释的三个**（文档口径）：向量相似度（dense cosine）、文本匹配分（批次内归一化 BM25）、
  图路径长度（`1/(1+hops)`，图未命中记 0）。不引入"没人能解释为什么进来"的特征。
- **没有标注数据就不训练**：样本数不足或标签单一直接拒绝（`ValueError`），不拿合成数据硬凑模型；
  上线门禁看交叉验证 AUC（`LTR_MIN_AUC`），在合成集上的数字只能证明工程行为可回归。
- **模型可追溯**：权重、样本数、指标、数据集摘要落库（`ranking_model`），激活 / 退役写治理审计，
  激活前自动校验门禁（不达标直接 409，不允许"手动绕过"）。

训练数据前置条件是 G2 的线上回流闭环：`evals.reflow` 人工标注晋级的真实语料集才是训练集来源。
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException

from ..config import settings

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_BLEND = "blend"
MODES = (MODE_OFF, MODE_SHADOW, MODE_BLEND)

# 特征就是文档点名的三个：向量相似度、图路径长度、文本匹配分。
FEATURE_NAMES = ("dense_similarity", "graph_proximity", "text_match")
FEATURE_TITLES = {
    "dense_similarity": "向量相似度（Dense 路 cosine，负值记 0）",
    "graph_proximity": "图路径长度（1/(1+hops)，图未命中记 0）",
    "text_match": "文本匹配分（BM25，批次内 min-max 归一化）",
}
# 图路径长度是"越小越好"，入特征时取倒数；未命中（hops 为空）与 0 跳区分开：
# 未命中给 0，命中给 1/(1+hops)，避免"没有图信号"被误当成"最优路径"。
UNKNOWN_PROXIMITY = 0.0


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp = math.exp(value)
    return exp / (1.0 + exp)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def graph_proximity(hops) -> float:
    """图路径长度特征：命中给 1/(1+hops)，未命中给 0（不是 1，避免"没图"排到最前）。"""
    if hops is None or hops == "":
        return UNKNOWN_PROXIMITY
    try:
        value = int(hops)
    except (TypeError, ValueError):
        return UNKNOWN_PROXIMITY
    if value < 1:
        return UNKNOWN_PROXIMITY
    return round(1.0 / (1.0 + value), 6)


def candidate_features(rows) -> list[dict]:
    """批次内特征提取：BM25 在同一批候选里 min-max 归一化。

    跨查询的 BM25 绝对值不可比，所以归一化只在本批内做；这也是"特征口径"的一部分，
    不允许把不同查询的分混在一起训练而不做归一化。
    """
    lexical = [max(0.0, float(row.get("bm25_score") or 0.0)) for row in rows]
    ceiling = max(lexical) if lexical else 0.0
    scale = ceiling if ceiling > 0 else 1.0
    features = []
    for row, score in zip(rows, lexical):
        dense = float(row.get("dense_score") or 0.0)
        features.append({
            "dense_similarity": round(clamp01(dense), 6),
            "graph_proximity": graph_proximity(row.get("graph_hops")),
            "text_match": round(clamp01(score / scale), 6),
        })
    return features


def _auc(scores, labels) -> float | None:
    positives = [score for score, label in zip(scores, labels) if label == 1]
    negatives = [score for score, label in zip(scores, labels) if label == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class TrainingSample:
    features: dict
    label: int

    def as_dict(self) -> dict:
        return {"features": {name: float(self.features.get(name, 0.0)) for name in FEATURE_NAMES}, "label": int(self.label)}


@dataclass(frozen=True)
class RankingModel:
    """一个可解释的线性排序模型（逻辑回归）：score = sigmoid(bias + Σ w·f)。"""

    version: str
    weights: dict
    bias: float
    features: tuple = FEATURE_NAMES
    metrics: dict = None
    samples: int = 0
    positives: int = 0
    trained_at: str = ""
    dataset_digest: str = ""

    def score(self, features: dict) -> float:
        total = float(self.bias)
        for name in self.features:
            total += float(self.weights.get(name, 0.0)) * float(features.get(name, 0.0))
        return round(_sigmoid(total), 6)

    def payload(self) -> dict:
        return {
            "version": self.version, "features": list(self.features), "weights": dict(self.weights),
            "bias": float(self.bias), "metrics": dict(self.metrics or {}), "samples": int(self.samples),
            "positives": int(self.positives), "trainedAt": self.trained_at,
            "datasetDigest": self.dataset_digest,
        }

    @classmethod
    def from_payload(cls, payload: dict) -> "RankingModel":
        return cls(
            version=str(payload.get("version") or ""),
            weights={name: float(value) for name, value in (payload.get("weights") or {}).items()},
            bias=float(payload.get("bias") or 0.0),
            features=tuple(payload.get("features") or FEATURE_NAMES),
            metrics=dict(payload.get("metrics") or {}),
            samples=int(payload.get("samples") or 0),
            positives=int(payload.get("positives") or 0),
            trained_at=str(payload.get("trainedAt") or ""),
            dataset_digest=str(payload.get("datasetDigest") or ""),
        )


def _fit(samples, *, epochs: int, learning_rate: float, l2: float) -> tuple[dict, float]:
    """纯拟合：梯度下降 + L2。折内小样本也走同一条路径，但门禁只在外层判。"""
    weights = {name: 0.0 for name in FEATURE_NAMES}
    bias = 0.0
    for _ in range(max(1, int(epochs))):
        gradients = {name: 0.0 for name in FEATURE_NAMES}
        bias_gradient = 0.0
        for sample in samples:
            features = sample.features
            probability = _sigmoid(
                bias + sum(weights[name] * float(features.get(name, 0.0)) for name in FEATURE_NAMES)
            )
            error = probability - int(sample.label)
            for name in FEATURE_NAMES:
                gradients[name] += error * float(features.get(name, 0.0))
            bias_gradient += error
        size = len(samples)
        for name in FEATURE_NAMES:
            weights[name] -= learning_rate * (gradients[name] / size + l2 * weights[name])
        bias -= learning_rate * bias_gradient / size
    return weights, bias


def _linear_score(weights, bias, features) -> float:
    return _sigmoid(bias + sum(
        float(weights.get(name, 0.0)) * float(features.get(name, 0.0)) for name in FEATURE_NAMES
    ))


def train_model(
    samples,
    *,
    epochs: int | None = None,
    learning_rate: float | None = None,
    l2: float = 1e-3,
    folds: int = 5,
    dataset_digest: str = "",
    groups=None,
) -> RankingModel:
    """逻辑回归训练 + k 折交叉验证。

    训练样本必须同时含正例与负例，且数量达到 `LTR_MIN_SAMPLES`：标注数据不够时直接拒绝，
    返回一个"看着能用"的模型比不返回模型更危险。
    """
    samples = list(samples)
    epochs = int(epochs if epochs is not None else settings.ltr_train_epochs)
    learning_rate = float(learning_rate if learning_rate is not None else settings.ltr_learning_rate)
    labels = {int(sample.label) for sample in samples}
    if not labels <= {0, 1}:
        raise ValueError("训练标签只能是 0 / 1")
    if labels != {0, 1}:
        raise ValueError("训练样本必须同时包含正例与负例，单类标签无法训练排序模型")
    for sample in samples:
        for name in FEATURE_NAMES:
            if not math.isfinite(float(sample.features.get(name, 0.0))):
                raise ValueError(f"特征 {name} 出现非有限值（NaN / Inf），拒绝训练")
    if len(samples) < int(settings.ltr_min_samples):
        raise ValueError(
            f"训练样本不足（{len(samples)} < LTR_MIN_SAMPLES={settings.ltr_min_samples}）："
            "先补齐 G2 线上回流标注数据，不要用合成数据硬凑"
        )

    weights, bias = _fit(samples, epochs=epochs, learning_rate=learning_rate, l2=l2)
    scores = [_linear_score(weights, bias, sample.features) for sample in samples]
    labels_list = [int(sample.label) for sample in samples]
    logloss = -sum(
        math.log(max(score, 1e-12)) if label else math.log(max(1.0 - score, 1e-12))
        for score, label in zip(scores, labels_list)
    ) / len(samples)
    accuracy = sum(1 for score, label in zip(scores, labels_list) if (score >= 0.5) == bool(label)) / len(samples)
    fold_count = int(folds)
    fold_scores, fold_labels, skipped_folds = [], [], 0
    fold_unit = "row"
    if groups is not None:
        # 按分组切折（典型分组 = query / case id）：同一查询的候选整组进同一折，
        # 否则"自己考自己"会让 AUC 虚高。训练接口与评测脚本都用这个口径。
        groups = list(groups)
        if len(groups) != len(samples):
            raise ValueError("groups 长度必须与训练样本数一致")
        keys = sorted({str(key) for key in groups})
        assignment = {key: index % fold_count for index, key in enumerate(keys)}
        buckets = [
            [sample for sample, key in zip(samples, groups) if assignment[str(key)] == fold]
            for fold in range(fold_count)
        ]
        fold_unit = "group"
    else:
        buckets = [
            [sample for position, sample in enumerate(samples) if position % fold_count == fold]
            for fold in range(fold_count)
        ]
    if fold_count > 1:
        for index in range(fold_count):
            held_out = buckets[index] if index < len(buckets) else []
            residuals = [sample for fold, bucket in enumerate(buckets) if fold != index for sample in bucket]
            if not held_out or not _fold_trainable(residuals):
                skipped_folds += 1
                continue
            fold_weights, fold_bias = _fit(
                residuals, epochs=epochs, learning_rate=learning_rate, l2=l2,
            )
            for sample in held_out:
                fold_scores.append(_linear_score(fold_weights, fold_bias, sample.features))
                fold_labels.append(int(sample.label))
    metrics = {
        "auc": _auc(scores, labels_list),
        "accuracy": round(accuracy, 6),
        "logloss": round(logloss, 6),
        "cv_auc": _auc(fold_scores, fold_labels),
        "cv_samples": len(fold_scores),
        "folds": fold_count,
        "skippedFolds": skipped_folds,
        # 折的划分单位：row（按样本取模）会偏乐观（同一 query 的候选跨折）；
        # group（按 query / case 分组）才是"样本外"的正确口径，见 foldUnit。
        "foldUnit": fold_unit,
        "epochs": int(epochs),
        "learningRate": float(learning_rate),
        "l2": float(l2),
        "inSample": True,
    }
    positives = sum(1 for label in labels_list if label == 1)
    version = f"ltr-{_digest({'weights': weights, 'bias': bias, 'samples': len(samples), 'digest': dataset_digest})}"
    return RankingModel(
        version=version, weights={name: round(value, 6) for name, value in weights.items()},
        bias=round(bias, 6), metrics=metrics, samples=len(samples), positives=positives,
        trained_at=datetime.now(timezone.utc).isoformat(), dataset_digest=dataset_digest,
    )


def _fold_trainable(samples) -> bool:
    labels = {int(sample.label) for sample in samples}
    return labels == {0, 1} and len(samples) >= 2


def should_promote(model: RankingModel | None, *, min_auc: float | None = None, min_samples: int | None = None,
                    cv_auc: float | None = None, fold_unit: str = "") -> dict:
    """上线门禁：样本外 AUC 达标才允许激活；不达标返回原因，不用话术替它通过。"""
    threshold = float(min_auc if min_auc is not None else settings.ltr_min_auc)
    required = int(min_samples if min_samples is not None else settings.ltr_min_samples)
    if model is None:
        return {"promoted": False, "reason": "no-model", "note": "没有已注册的排序模型"}
    metrics = model.metrics or {}
    # 允许调用方传入更严格的折外口径（例如按 case 分折的 pooled AUC）覆盖模型自带指标；
    # 传入什么口径就报什么口径，不允许用行级折的数字冒充 case 级折外。
    if cv_auc is None:
        cv_auc = metrics.get("cv_auc")
    fold_unit = fold_unit or str(metrics.get("foldUnit") or "")
    reasons = []
    if model.samples < required:
        reasons.append(f"训练样本不足（{model.samples} < {required}）")
    if cv_auc is None:
        reasons.append("缺少交叉验证 AUC（标注数据不足以做样本外评估）")
    elif float(cv_auc) < threshold:
        reasons.append(f"样本外 AUC {cv_auc} < LTR_MIN_AUC={threshold}")
    return {
        "promoted": not reasons,
        "reason": "; ".join(reasons) or "ok",
        "cvAuc": cv_auc,
        "foldUnit": fold_unit,
        "minAuc": threshold,
        "samples": model.samples,
        "minSamples": required,
        "note": (
            "门禁通过：可按 LTR_MODE=shadow 先跑影子，再小步提高 LTR_BLEND_ALPHA 切到 blend。"
            if not reasons else
            "门禁未通过：保持 RRF 保底（LTR_MODE=off），先补标注数据与样本外增益证据。"
        ),
    }


def configured_mode() -> str:
    mode = (settings.ltr_mode or MODE_OFF).strip().lower()
    return mode if mode in MODES else MODE_OFF


def active_mode() -> tuple[str, str]:
    """当前生效模式与原因；运行时开关显式关闭时退化为 off 并给出原因。"""
    mode = configured_mode()
    if mode == MODE_OFF:
        return MODE_OFF, ""
    from .runtime_flags import disabled
    if disabled("ltr"):
        return MODE_OFF, "runtime-flag-ltr-off"
    return mode, ""


def rank(rows, *, mode: str, model: RankingModel | None, alpha: float | None = None, top_k: int = 6) -> tuple[list, dict]:
    """按模式给候选排序；返回 (新顺序列表, 诊断)。任何异常都必须退化成 RRF 原序。"""
    rows = list(rows)
    alpha = float(alpha if alpha is not None else settings.ltr_blend_alpha)
    diagnostics = {
        "mode": mode or MODE_OFF, "alpha": alpha, "model": None, "modelVersion": "",
        "shadowTopChanged": 0, "degraded": False, "reason": "",
    }
    if mode not in {MODE_SHADOW, MODE_BLEND} or not rows:
        diagnostics["mode"] = MODE_OFF
        return rows, diagnostics
    try:
        if model is None:
            diagnostics.update(mode=MODE_OFF, degraded=True, reason="no-active-model")
            return rows, diagnostics
        features = candidate_features(rows)
        scores = [model.score(feature) for feature in features]
        rrf = [max(0.0, float(row.get("rrf_score") or 0.0)) for row in rows]
        # 非有限分数（NaN / Inf）一律视为模型异常：退回 RRF，不把 NaN 写进响应 JSON。
        if not all(math.isfinite(score) for score in scores) or not all(math.isfinite(v) for v in rrf):
            raise ValueError("non-finite ranking score")
        ceiling = max(rrf) if rrf else 0.0
        scale = ceiling if ceiling > 0 else 1.0
        for row, feature, score, rrf_score in zip(rows, features, scores, rrf):
            row["ltr_features"] = feature
            row["ltr_score"] = score
            # 混合分保底：RRF 权重 (1-alpha) 始终占大头；alpha 上限由配置约束，不在此处放大。
            row["blend_score"] = round((1.0 - alpha) * (rrf_score / scale) + alpha * score, 6)
        ordered = sorted(
            rows,
            key=lambda row: (-float(row["blend_score"]), -float(row.get("rrf_score") or 0.0),
                             getattr(row.get("clause"), "id", 0)),
        )
        diagnostics.update(
            model="linear-logistic", modelVersion=model.version,
            shadowTopChanged=_top_set_delta(rows, ordered, top_k),
        )
        if mode == MODE_SHADOW:
            # 影子模式只记录"如果启用会怎样"，线上顺序仍然是 RRF。
            return rows, diagnostics
        return ordered, diagnostics
    except Exception as exc:  # noqa: BLE001  LTR 是增强项，异常不得影响检索可用性
        diagnostics.update(mode=MODE_OFF, degraded=True, reason=type(exc).__name__)
        return rows, diagnostics


def _top_set_delta(before, after, top_k: int) -> int:
    def identity(row):
        clause = row.get("clause")
        return getattr(clause, "id", id(clause))
    size = max(1, min(int(top_k), len(before)))
    head_before = [identity(row) for row in before[:size]]
    head_after = [identity(row) for row in after[:size]]
    return len(set(head_before) ^ set(head_after)) // 2


# ===== 模型持久化（版本 / 审计 / 回滚）=====

_ACTIVE_CACHE: dict = {}


def invalidate_cache() -> None:
    _ACTIVE_CACHE.clear()


def save_model(db, model: RankingModel, *, status: str = "shadow", domain: str = "policy",
               tenant_id: str = "", notes: str = ""):
    from .platform_models import RankingModelRecord as RankingModelRow
    # active 只能由 activate_model 产生（那里跑门禁 + 写审计）；
    # 离线脚本落库也只能写 shadow / retired，不允许"绕过门禁直接上线"。
    if status not in {"shadow", "retired"}:
        raise HTTPException(422, "save_model 只能写 shadow / retired；上线必须走 activate_model")
    if not math.isfinite(float(model.bias)):
        raise HTTPException(422, "模型 bias 非有限值")
    for name, weight in model.weights.items():
        if name not in FEATURE_NAMES:
            raise HTTPException(422, f"未知特征：{name}")
        if not math.isfinite(float(weight)):
            raise HTTPException(422, f"权重 {name} 非有限值")
    if int(model.positives) > int(model.samples):
        raise HTTPException(422, "positives 不能大于 samples")
    row = db.get(RankingModelRow, model.version)
    if row is not None:
        # 同版本必须同内容：否则一次"重复注册"就能静默改掉线上权重（并可能把 active 打回 shadow）。
        if row.domain != domain or row.tenant_id != tenant_id:
            raise HTTPException(409, "ranking model version belongs to another scope")
        if (dict(row.weights or {}) != dict(model.weights) or float(row.bias) != float(model.bias)
                or list(row.features or []) != list(model.features)):
            raise HTTPException(409, "ranking model version already exists with different weights")
        row.metrics = dict(model.metrics or {})
        row.notes = notes[:500]
        row.dataset_digest = model.dataset_digest
        db.flush()
        invalidate_cache()
        return row
    row = RankingModelRow(id=model.version)
    db.add(row)
    row.domain, row.tenant_id, row.status = domain, tenant_id, status
    row.features = list(model.features)
    row.weights = dict(model.weights)
    row.bias = float(model.bias)
    row.samples = int(model.samples)
    row.positives = int(model.positives)
    row.metrics = dict(model.metrics or {})
    row.dataset_digest = model.dataset_digest
    row.notes = notes[:500]
    row.trained_at = _parse_time(model.trained_at)
    row.activated_at = None
    db.flush()
    invalidate_cache()
    return row


def _parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).replace(tzinfo=None)


def load_active(db, *, domain: str = "policy", tenant_id: str = "") -> RankingModel | None:
    """读取当前激活模型（进程内缓存，激活 / 退役时失效）。"""
    key = (id(db.get_bind()), domain, tenant_id)
    if key not in _ACTIVE_CACHE:
        from .platform_models import RankingModelRecord as RankingModelRow
        row = db.query(RankingModelRow).filter(
            RankingModelRow.domain == domain, RankingModelRow.tenant_id == tenant_id,
            RankingModelRow.status == "active",
        ).order_by(RankingModelRow.activated_at.desc(), RankingModelRow.id.desc()).first()
        _ACTIVE_CACHE[key] = RankingModel.from_payload({
            "version": row.id, "features": row.features, "weights": row.weights, "bias": row.bias,
            "metrics": row.metrics, "samples": row.samples, "positives": row.positives,
            "trainedAt": row.trained_at.isoformat() if row.trained_at else "",
            "datasetDigest": row.dataset_digest,
        }) if row else None
    return _ACTIVE_CACHE[key]


def activate_model(db, version: str, *, domain: str = "policy", tenant_id: str = "", operator: str = "",
                   force: bool = False) -> dict:
    """激活一个模型版本：门禁不通过直接 409（`force` 仅供受控回滚到已验证版本）。"""
    from .governance import audit
    from .platform_models import RankingModelRecord as RankingModelRow
    row = db.get(RankingModelRow, version)
    if row is None or row.domain != domain or row.tenant_id != tenant_id:
        raise HTTPException(404, "ranking model not found")
    if row.status == "retired" and row.activated_at is None:
        # 从未激活过却被标 retired：属于数据异常，直接拒绝（回滚只针对"曾经上线过"的版本）。
        raise HTTPException(409, "never-activated model cannot be activated")
    model = RankingModel.from_payload({
        "version": row.id, "features": row.features, "weights": row.weights, "bias": row.bias,
        "metrics": row.metrics, "samples": row.samples, "positives": row.positives,
        "trainedAt": row.trained_at.isoformat() if row.trained_at else "",
        "datasetDigest": row.dataset_digest,
    })
    decision = should_promote(model)
    if not decision["promoted"] and not force:
        raise HTTPException(409, detail={"message": "排序模型未通过上线门禁", **decision})
    if not decision["promoted"] and row.activated_at is None:
        # force 是"回滚到已验证版本"的通道，不是"绕过门禁上线新模型"的后门。
        raise HTTPException(409, detail={
            "message": "force 只允许回滚曾激活过的版本；未验证过的新模型必须先过门禁",
            "version": version, **decision,
        })
    previous = [item.id for item in db.query(RankingModelRow).filter(
        RankingModelRow.domain == domain, RankingModelRow.tenant_id == tenant_id,
        RankingModelRow.status == "active",
    ).all()]
    for item in db.query(RankingModelRow).filter(
        RankingModelRow.id.in_(previous),
    ).all():
        item.status = "retired"
    row.status = "active"
    row.activated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    audit(db, "ltr.activate", f"ranking-model:{version}", details={
        "previousActive": previous, "gate": decision["promoted"], "forced": bool(force),
        "cvAuc": decision.get("cvAuc"), "samples": model.samples, "operator": operator[:64],
    })
    db.flush()
    invalidate_cache()
    return {"version": version, "status": "active", "retired": previous, "gate": decision}


def retire_model(db, version: str, *, domain: str = "policy", tenant_id: str = "", operator: str = "") -> dict:
    from .governance import audit
    from .platform_models import RankingModelRecord as RankingModelRow
    row = db.get(RankingModelRow, version)
    # 与 activate 对称：跨域 / 跨租户的版本不允许被退役，否则 A 租户能下线 B 租户的模型。
    if row is None or row.domain != domain or row.tenant_id != tenant_id:
        raise HTTPException(404, "ranking model not found")
    row.status = "retired"
    audit(db, "ltr.retire", f"ranking-model:{version}", details={"operator": operator[:64]})
    db.flush()
    invalidate_cache()
    return {"version": version, "status": "retired"}


def model_rows(db, *, domain: str = "policy", tenant_id: str = "", limit: int = 50) -> list[dict]:
    from .platform_models import RankingModelRecord as RankingModelRow
    rows = db.query(RankingModelRow).filter(
        RankingModelRow.domain == domain, RankingModelRow.tenant_id == tenant_id,
    ).order_by(RankingModelRow.trained_at.desc(), RankingModelRow.id.desc()).limit(max(1, min(int(limit), 200))).all()
    return [{
        "version": row.id, "status": row.status, "features": row.features, "weights": row.weights,
        "bias": row.bias, "samples": row.samples, "positives": row.positives, "metrics": row.metrics,
        "datasetDigest": row.dataset_digest, "notes": row.notes,
        "trainedAt": row.trained_at, "activatedAt": row.activated_at,
    } for row in rows]


def snapshot(db, *, domain: str = "policy", tenant_id: str = "") -> dict:
    """LTR 现状：模式、alpha、门禁阈值、当前激活模型与历史版本。"""
    model = load_active(db, domain=domain, tenant_id=tenant_id)
    return {
        "mode": configured_mode(),
        "effectiveMode": active_mode()[0],
        "modeReason": active_mode()[1],
        "blendAlpha": float(settings.ltr_blend_alpha),
        "features": [{"name": name, "title": FEATURE_TITLES[name]} for name in FEATURE_NAMES],
        "gate": {
            "minSamples": int(settings.ltr_min_samples), "minAuc": float(settings.ltr_min_auc),
            "note": "样本外（交叉验证）AUC 是唯一上线依据；合成集指标只证明工程行为可回归。",
        },
        "activeModel": model.payload() if model else None,
        "models": model_rows(db, domain=domain, tenant_id=tenant_id),
        "fallback": "off / 模型缺失 / 任何异常都退回 RRF 顺序，并把 degraded 原因写进检索诊断。",
    }