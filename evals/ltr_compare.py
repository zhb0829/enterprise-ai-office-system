"""LTR 增益对比（G9 验收方式）：RRF 保底 vs LTR 渐进替换。

口径纪律（与 `evals/README.md`、`evals/graph_gain.py` 一致）：

- 数据集默认用合成图谱语料（`policy_graph_*`），只证明**工程行为可回归**，
  不证明真实检索质量；真实上线依据必须是 `--dataset-file evals/datasets/reflow/real-*.json`
  （G2 回流人工标注集）。
- 三个受控口径，唯一变量是排序函数：
  - `rrf`：现有 RRF 保底顺序（基线）。
  - `ltr_shadow`：算 LTR 分并记录影子排序差异，**线上顺序仍是 RRF**。
  - `ltr_blend`：`(1-alpha)·RRF + alpha·LTR` 重排（候选池内，池子大小与 RRF 口径一致）。
- **样本外**：按 case 做 k 折，折内 case 的排序只用其他折样本训练出的模型，避免"自己考自己"；
  报告同时给出 in-sample 指标，但标注 `inSample`，不得作为上线依据。
- 训练数据不足（`LTR_MIN_SAMPLES`）或标签单一：**不训练**，报告 `promoted=false`，
  并指向 G2 回流闭环——没有标注数据就不该有一个排序模型。
- 上线门禁看样本外 AUC（`LTR_MIN_AUC`）：不达标时 `--require-gain` 返回非零退出码。

```powershell
.venv\\Scripts\\python.exe -m evals.ltr_compare --output evals/reports/ltr-compare.json
.venv\\Scripts\\python.exe -m evals.ltr_compare --dataset-file evals/datasets/reflow/real-2026-10-25.json
.venv\\Scripts\\python.exe -m evals.ltr_compare --require-gain   # CI 门禁口径
```
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from .graph_gain import DEFAULT_AS_OF, load, seed_corpus
from .metrics import average, retrieval_metrics

OFFLINE_SETTINGS = ("llm_api_key", "embedding_api_key", "rerank_url", "rerank_api_key", "rerank_local_model")
METRIC_KEYS = ("recall_at_k", "mrr", "ndcg_at_k")
FUSION_SOURCES = ("lexical", "dense", "graph")
CANDIDATE_LIMIT = 20
TOP_K = 6
EPSILON = 1e-9
FOLDS = 5


def _dataset(name):
    if name == "graph":
        return load("policy_graph_corpus.json")["documents"], load("policy_graph_qa.json")
    if name == "policy":
        return load("policy_corpus.json")["documents"], load("policy_qa.json")
    payload = json.loads(Path(name).read_text(encoding="utf-8-sig"))
    return payload.get("corpus") or [], payload


def digest_of(documents, cases):
    payload = json.dumps({"documents": documents, "cases": cases}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def collect_candidates(db, mapping, raw_cases, *, limit=CANDIDATE_LIMIT, sources=FUSION_SOURCES):
    """一次检索拿到候选池 + 口径内特征；标注命中的条款为正例。"""
    from app.schemas import PolicyQuery
    from app.services.policy import search_policy_clauses

    cases = []
    for case in raw_cases:
        request = PolicyQuery.model_validate({"asOf": DEFAULT_AS_OF, **case})
        hits = search_policy_clauses(
            db, request.question, industry=request.industry, level=request.level,
            authority=request.authority, limit=limit, region=getattr(request, "region", ""),
            policy_name=getattr(request, "policyName", ""), as_of=getattr(request, "asOf", None),
            fusion_sources=sources,
        )
        expected = {tuple(item) for item in case["expected"]}
        rows = []
        for hit in hits:
            retrieval = hit.get("retrieval") or {}
            identity = mapping.get(hit["clause"].id)
            rows.append({
                "key": identity, "clauseId": hit["clause"].id,
                "relevant": identity in expected,
                "bm25_score": float(retrieval.get("bm25") or 0.0),
                "dense_score": float(retrieval.get("dense") or 0.0),
                "graph_hops": retrieval.get("graphHops"),
                "rrf": float(retrieval.get("rrf") or 0.0),
            })
        cases.append({
            "id": case["id"], "question": case["question"], "rows": rows,
            "expected": [list(item) for item in case["expected"]],
            "graph": (hits[0]["retrieval"].get("graph") if hits else None),
        })
    return cases


def _rank(rows, key, limit=TOP_K):
    ordered = sorted(rows, key=lambda row: (-float(row.get(key) or 0.0), -float(row.get("rrf") or 0.0)))
    return [row["key"] for row in ordered[:limit]]


def _top_delta(before, after, size=TOP_K):
    head_before = {row["key"] for row in before[:max(1, min(size, len(before)))]}
    head_after = {row["key"] for row in after[:max(1, min(size, len(after)))]}
    return len(head_before ^ head_after) // 2


def _ordered_by_blend(rows, model, alpha):
    from app.agent import ltr as ranking
    features = ranking.candidate_features(rows)
    scores = [model.score(feature) for feature in features]
    rrf = [max(0.0, float(row.get("rrf") or 0.0)) for row in rows]
    ceiling = max(rrf) if rrf else 0.0
    scale = ceiling if ceiling > 0 else 1.0
    blended = [
        {**row, "ltr_score": score,
         "blend": (1.0 - alpha) * (rrf_score / scale) + alpha * score}
        for row, score, rrf_score in zip(rows, scores, rrf)
    ]
    return sorted(blended, key=lambda row: (-float(row["blend"]), -float(row.get("rrf") or 0.0)))


def cross_validate(cases, *, folds=FOLDS, alpha=0.3):
    """按 case 分折：折内排序只用其他折训练出的模型，得到样本外指标。"""
    from app.agent import ltr as ranking

    results = {"rrf": [], "ltr_shadow": [], "ltr_blend": []}
    fold_notes, trained_folds, skipped_folds = [], 0, 0
    pooled_scores, pooled_labels = [], []
    total_samples = sum(len(case["rows"]) for case in cases)
    for index in range(folds):
        held_out = [case for position, case in enumerate(cases) if position % folds == index]
        residuals = [case for position, case in enumerate(cases) if position % folds != index]
        if not held_out:
            continue
        samples = [
            ranking.TrainingSample(features=feature, label=1 if row["relevant"] else 0)
            for case in residuals
            for row, feature in zip(case["rows"], ranking.candidate_features(case["rows"]))
        ]
        model = None
        reason = ""
        try:
            model = ranking.train_model(samples, folds=0)
            trained_folds += 1
        except ValueError as exc:
            skipped_folds += 1
            reason = str(exc)
        fold_notes.append({
            "fold": index, "heldOut": len(held_out), "trainSamples": len(samples),
            "trained": model is not None, "reason": reason,
            # 该折模型的"训练集内" AUC；折外表现看 pooledCaseAuc（按 case 收集）
            "trainAuc": (model.metrics or {}).get("auc") if model else None,
        })
        for case in held_out:
            expected = [tuple(item) for item in case["expected"]]
            rows = case["rows"]
            if model is not None:
                # 折外（held-out case）的逐候选打分：pooled AUC 用这批分算，才是真折外。
                for row, feature in zip(rows, ranking.candidate_features(rows)):
                    pooled_scores.append(model.score(feature))
                    pooled_labels.append(1 if row["relevant"] else 0)
            results["rrf"].append(retrieval_metrics(_rank(rows, "rrf"), expected, k=TOP_K))
            if model is None:
                results["ltr_shadow"].append(retrieval_metrics(_rank(rows, "rrf"), expected, k=TOP_K))
                results["ltr_blend"].append(retrieval_metrics(_rank(rows, "rrf"), expected, k=TOP_K))
                continue
            ordered = _ordered_by_blend(rows, model, alpha)
            rrf_order = sorted(rows, key=lambda row: (-float(row.get("rrf") or 0.0)))
            results["ltr_shadow"].append({
                **retrieval_metrics(_rank(rows, "rrf"), expected, k=TOP_K),
                "shadow_top_changed": _top_delta(rrf_order, ordered),
            })
            results["ltr_blend"].append(retrieval_metrics(_rank(ordered, "blend"), expected, k=TOP_K))
    summary = {
        key: {**{name: average([item.get(name) for item in rows]) for name in METRIC_KEYS},
              "cases": len(rows),
              "shadow_top_changed_avg": average([item.get("shadow_top_changed") for item in rows])}
        for key, rows in results.items()
    }
    return summary, fold_notes, {
        "totalSamples": total_samples, "trainedFolds": trained_folds, "skippedFolds": skipped_folds,
        "foldUnit": "case", "pooledCaseAuc": ranking._auc(pooled_scores, pooled_labels),
        "pooledSamples": len(pooled_scores),
    }


def in_sample(cases, *, alpha=0.3):
    """全量训练后在同一批数据上打分：只作参考，报告里必须标 inSample。

    训练时按 case 传 groups：交叉验证按查询分组切折，AUC 才是"没见过的查询"上的表现；
    否则同一 query 的候选跨折，AUC 会虚高（`foldUnit` 会如实写 group / row）。
    """
    from app.agent import ltr as ranking

    samples, groups = [], []
    for case in cases:
        features = ranking.candidate_features(case["rows"])
        for row, feature in zip(case["rows"], features):
            samples.append(ranking.TrainingSample(features=feature, label=1 if row["relevant"] else 0))
            groups.append(str(case["id"]))
    try:
        model = ranking.train_model(samples, groups=groups)
    except ValueError as exc:
        return {"trained": False, "reason": str(exc), "model": None,
                "gate": ranking.should_promote(None)}
    metrics = {"recall_at_k": [], "mrr": [], "ndcg_at_k": []}
    for case in cases:
        expected = [tuple(item) for item in case["expected"]]
        ordered = _ordered_by_blend(case["rows"], model, alpha)
        result = retrieval_metrics(_rank(ordered, "blend"), expected, k=TOP_K)
        for name in metrics:
            metrics[name].append(result[name])
    return {
        "trained": True, "inSample": True, "model": model.payload(),
        "gate": ranking.should_promote(model),
        "metrics": {name: average(values) for name, values in metrics.items()},
    }


def decide(variants, gate):
    baseline = variants["rrf"]["summary"]
    shadow = variants["ltr_shadow"]["summary"]
    treatment = variants["ltr_blend"]["summary"]
    recall_gain = (treatment["recall_at_k"] or 0.0) - (baseline["recall_at_k"] or 0.0)
    mrr_gain = (treatment["mrr"] or 0.0) - (baseline["mrr"] or 0.0)
    ndcg_gain = (treatment["ndcg_at_k"] or 0.0) - (baseline["ndcg_at_k"] or 0.0)
    passed = recall_gain > EPSILON or (abs(recall_gain) <= EPSILON and (mrr_gain > EPSILON or ndcg_gain > EPSILON))
    promoted = bool(passed and gate.get("promoted"))
    return {
        "baseline": "rrf", "treatment": "ltr_blend", "reference": "ltr_shadow",
        "recall_gain": round(recall_gain, 6), "mrr_gain": round(mrr_gain, 6),
        "ndcg_gain": round(ndcg_gain, 6),
        "shadow_top_changed_avg": shadow.get("shadow_top_changed_avg"),
        "outOfSampleGain": passed,
        "gatePromoted": bool(gate.get("promoted")),
        "promoted": promoted,
        "note": (
            "增益与门禁同时通过：可先按 LTR_MODE=shadow 上线影子，再小步提高 LTR_BLEND_ALPHA 切 blend。"
            if promoted else
            "未达上线条件：保持 RRF 保底（LTR_MODE=off）。"
            + ("增益未达标；" if not passed else "")
            + (f"门禁未通过（{gate.get('reason')}）；" if not gate.get("promoted") else "")
        ),
    }


def build_report(mode, dataset_name, documents, raw_cases, variants, gate, training):
    return {
        "dataset": dataset_name, "dataset_source": "synthetic" if mode == "offline" else "configured",
        "dataset_digest": digest_of(documents, raw_cases),
        "mode": mode, "generated_at": datetime.now().isoformat(),
        "synthetic": mode == "offline",
        "scope": "engineering-regression-only",
        "application": "engineering-regression-only" if mode == "offline" else "quality-acceptance-candidate",
        "candidateLimit": CANDIDATE_LIMIT, "topK": TOP_K, "fusionSources": list(FUSION_SOURCES),
        "folds": FOLDS,
        "shadowTopChangedMetric": "前 K 名集合的对称差 / 2（度量的是集合变化，不是名次顺序变化）",
        "metricCaveat": (
            "正例稀少（合成集 8 正例 / 92 候选）时 accuracy 会被\"全猜负例\"抬高，"
            "结论只看 AUC；这是工程回归口径，不是真实检索质量验收。"
        ),
        "note": (
            "候选池口径是单次检索 top-20（在线是整池），features 归一化在本批候选内完成；"
            "上线依据必须是真实回流标注集的样本外增益。"
        ),
        "variants": variants,
        "inSampleReference": training,
        "gate": gate,
        "decision": decide(variants, gate),
    }


def evaluate(dataset="graph", mode="offline"):
    with ExitStack() as stack:
        environment = {"APP_ENV": "test"}
        if mode == "offline":
            environment.update({name.upper(): "" for name in OFFLINE_SETTINGS})
        stack.enter_context(patch.dict(os.environ, environment))
        return _evaluate(dataset, mode, stack)


def _evaluate(dataset, mode, stack):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app import models as business_models  # noqa: F401  注册业务表，create_all 需要
    from app.agent import ltr as ranking
    from app.agent import models as agent_models  # noqa: F401
    from app.agent import platform_models  # noqa: F401
    from app.config import settings
    from app.db import Base
    from app.kg import models as kg_models  # noqa: F401
    from app.kg.build import build_graph

    if mode == "offline":
        for name in OFFLINE_SETTINGS:
            stack.enter_context(patch.object(settings, name, ""))
    if mode == "live" and not settings.llm_api_key:
        raise RuntimeError("Live LTR evaluation requires a configured extraction model")

    documents, payload = _dataset(dataset)
    raw_cases = payload["cases"]
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    variants = {}
    with Session(engine) as db:
        mapping = seed_corpus(db, documents)
        if dataset == "graph":
            build_graph(db, tenant_id="default")
        cases = collect_candidates(db, mapping, raw_cases)
    engine.dispose()
    summary, folds, training_stats = cross_validate(cases)
    training = in_sample(cases)
    variants["rrf"] = {"summary": summary["rrf"], "cases": summary["rrf"]["cases"]}
    variants["ltr_shadow"] = {"summary": summary["ltr_shadow"]}
    variants["ltr_blend"] = {"summary": summary["ltr_blend"]}
    gate = {
        **(training.get("gate") or {"promoted": False, "reason": "unknown"}),
        "folds": folds,
        "cvAuc": (training.get("model") or {}).get("metrics", {}).get("cv_auc") if training.get("trained") else None,
        "cvSource": (
            "kfold-by-" + str(((training.get("model") or {}).get("metrics") or {}).get("foldUnit", "row"))
            + "-out-of-fold"
        ) if training.get("trained") else "not-trained",
        "scope": (
            "模型区分度门禁：样本量 + 折外（k 折）AUC。它只回答\"这个模型有没有区分度\"，"
            "不代表检索有增益——是否上线由 decision 的样本外检索增益决定。"
        ),
    }
    gate["promoted"] = bool((training.get("gate") or {}).get("promoted"))
    report = build_report(mode, dataset, documents, raw_cases, variants, gate, training)
    report["trainingStats"] = training_stats
    report["gate"]["minSamples"] = int(settings.ltr_min_samples)
    report["gate"]["minAuc"] = float(settings.ltr_min_auc)
    report["trainingStats"]["learnedWeights"] = (training.get("model") or {}).get("weights")
    return report


def main():
    parser = argparse.ArgumentParser(description="LTR 增益对比（G9 验收方式）")
    parser.add_argument("--dataset", default="graph", help="graph / policy / 或数据集文件路径")
    parser.add_argument("--dataset-file", default="", help="外部数据集（如 G2 回流 real-*.json）")
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--output", default="evals/reports/ltr-compare.json")
    parser.add_argument("--require-gain", action="store_true", help="未通过增益与门禁时返回非零退出码")
    args = parser.parse_args()
    dataset = args.dataset_file or args.dataset
    report = evaluate(dataset, args.mode)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    decision = report["decision"]
    print(json.dumps({
        "promoted": decision["promoted"], "output": str(target),
        "recall_gain": decision["recall_gain"], "mrr_gain": decision["mrr_gain"],
        "ndcg_gain": decision["ndcg_gain"], "gate": report["gate"].get("promoted"),
        "training": report["trainingStats"],
    }, ensure_ascii=False))
    raise SystemExit(1 if (args.require_gain and not decision["promoted"]) else 0)


if __name__ == "__main__":
    main()