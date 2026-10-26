"""图谱增益对比（G1 验收方式）：纯向量 vs 向量 + 图。

口径纪律（与 `evals/README.md` 一致）：

- 合成语料 + 合成用例，只证明"工程行为可回归"，不证明真实语义检索质量。
- 三个受控口径，唯一变量是 RRF 的融合来源：
  - `dense_only`：纯向量（问题要求的对比基线）
  - `lexical_dense`：现有主链路（BM25 + Dense + RRF）
  - `lexical_dense_graph`：在现有主链路之上加图谱遍历第三路
- `promoted` 只在"向量 + 图"相对"纯向量"取得 Recall@K 或 MRR 正向增益时为真；
  没有增益就写 `promoted: false`——无增益不上线，不靠话术上线。
- 离线模式强制关闭付费模型（构图走规则化通道，抽取后端记 `rule`）；
  `--mode live` 需要模型配置与调用预算审批，报告里会改成质量验收候选口径。

```powershell
.venv\\Scripts\\python.exe -m evals.graph_gain --output evals/reports/graph-gain.json
# CI 门禁口径：无增益返回非零退出码
.venv\\Scripts\\python.exe -m evals.graph_gain --require-gain
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

from .metrics import average, retrieval_metrics

DATASETS = Path(__file__).parent / "datasets"
OFFLINE_SETTINGS = ("llm_api_key", "embedding_api_key", "rerank_url", "rerank_api_key", "rerank_local_model")
METRIC_KEYS = ("recall_at_k", "mrr", "ndcg_at_k")
DEFAULT_AS_OF = "2026-10-11"
VARIANTS: dict[str, tuple[str, ...]] = {
    "dense_only": ("dense",),
    "lexical_dense": ("lexical", "dense"),
    "lexical_dense_graph": ("lexical", "dense", "graph"),
}
BASELINE_VARIANT = "dense_only"
REFERENCE_VARIANT = "lexical_dense"
TREATMENT_VARIANT = "lexical_dense_graph"
EPSILON = 1e-9


def load(name):
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))


def canonical_digest(documents, cases):
    payload = json.dumps({"documents": documents, "cases": cases}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def summarize(cases):
    summary = {key: average([case.get(key) for case in cases]) for key in METRIC_KEYS}
    summary["cases"] = len(cases)
    summary["degraded_graph_cases"] = sum(
        1 for case in cases if (case.get("graph") or {}).get("degraded")
    )
    return summary


def evaluate_cases(db, mapping, raw_cases, sources):
    from app.schemas import PolicyQuery
    from app.services.policy import search_policy_clauses

    cases = []
    for case in raw_cases:
        request = PolicyQuery.model_validate({"asOf": DEFAULT_AS_OF, **case})
        hits = search_policy_clauses(
            db, request.question, industry=request.industry, level=request.level,
            authority=request.authority, limit=request.limit,
            region=getattr(request, "region", ""), policy_name=getattr(request, "policyName", ""),
            as_of=getattr(request, "asOf", None), fusion_sources=sources,
        )
        retrieved = [mapping[hit["clause"].id] for hit in hits]
        metrics = retrieval_metrics(retrieved, [tuple(item) for item in case["expected"]])
        diagnostics = (hits[0]["retrieval"].get("graph") if hits else None) or {}
        cases.append({
            "id": case["id"], "question": case["question"], "sources": list(sources),
            **metrics, "retrieved": retrieved, "expected": case["expected"],
            "graph": {
                "enabled": bool(diagnostics.get("enabled")),
                "degraded": bool(diagnostics.get("degraded")),
                "seeds": diagnostics.get("seeds"),
                "matched": diagnostics.get("matched"),
                "paths": diagnostics.get("paths"),
            } if diagnostics.get("enabled") else None,
        })
    return cases


def decide(variants):
    baseline = variants[BASELINE_VARIANT]["summary"]
    reference = variants[REFERENCE_VARIANT]["summary"]
    treatment = variants[TREATMENT_VARIANT]["summary"]
    recall_gain = (treatment["recall_at_k"] or 0.0) - (baseline["recall_at_k"] or 0.0)
    mrr_gain = (treatment["mrr"] or 0.0) - (baseline["mrr"] or 0.0)
    promoted = recall_gain > EPSILON or (abs(recall_gain) <= EPSILON and mrr_gain > EPSILON)
    reference_recall_gain = (treatment["recall_at_k"] or 0.0) - (reference["recall_at_k"] or 0.0)
    reference_mrr_gain = (treatment["mrr"] or 0.0) - (reference["mrr"] or 0.0)
    return {
        "baseline": BASELINE_VARIANT,
        "treatment": TREATMENT_VARIANT,
        "reference": REFERENCE_VARIANT,
        "recall_gain_vs_vector": round(recall_gain, 6),
        "mrr_gain_vs_vector": round(mrr_gain, 6),
        "recall_gain_vs_lexical_dense": round(reference_recall_gain, 6),
        "mrr_gain_vs_lexical_dense": round(reference_mrr_gain, 6),
        "promoted": promoted,
        "note": (
            "有正向增益：可按 settings.kg_enabled=true 上线，并保留本报告作为上线依据。"
            if promoted else
            "无增益：按 G1 验收口径不上线，settings.kg_enabled 保持 false；"
            "如需上线必须先在真实语料回流集（--mode live）复测出增益。"
        ),
        "summary_line": {
            "vector_recall": baseline["recall_at_k"], "vector_mrr": baseline["mrr"],
            "graph_recall": treatment["recall_at_k"], "graph_mrr": treatment["mrr"],
            "lexical_dense_recall": reference["recall_at_k"], "lexical_dense_mrr": reference["mrr"],
        },
    }


def build_report(mode, meta, documents, raw_cases, variants, graph_result):
    return {
        "dataset_version": meta.get("version", "synthetic-graph-v1"),
        "dataset_source": "synthetic",
        "dataset_digest": canonical_digest(documents, raw_cases),
        "synthetic": True,
        "mode": mode,
        "generated_at": datetime.now().isoformat(),
        "scope": (
            "Synthetic relationship-reasoning corpus; engineering regression only, "
            "not real policy accuracy or production acceptance"
        ),
        "application": "engineering-regression-only" if mode == "offline" else "quality-acceptance-candidate",
        "graph_build": {key: value for key, value in graph_result.items() if key != "communities"},
        "graph_communities": graph_result.get("communities"),
        "variants": variants,
        "decision": decide(variants),
    }


def evaluate(mode="offline"):
    with ExitStack() as stack:
        environment = {"APP_ENV": "test"}
        if mode == "offline":
            environment.update({name.upper(): "" for name in OFFLINE_SETTINGS})
        stack.enter_context(patch.dict(os.environ, environment))
        return _evaluate(mode, stack)


def _evaluate(mode, stack):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app import models as business_models  # noqa: F401  注册业务表，create_all 需要
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
        raise RuntimeError("Live graph evaluation requires a configured extraction model")
    documents = load("policy_graph_corpus.json")["documents"]
    raw_cases = load("policy_graph_qa.json")["cases"]
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    variants = {}
    with Session(engine) as db:
        mapping = seed_corpus(db, documents)
        graph_result = build_graph(db, tenant_id="default")
        for name, sources in VARIANTS.items():
            cases = evaluate_cases(db, mapping, raw_cases, sources)
            variants[name] = {"sources": list(sources), "summary": summarize(cases), "cases": cases}
    engine.dispose()
    return build_report(mode, load("policy_graph_qa.json"), documents, raw_cases, variants, graph_result)


def seed_corpus(db, documents):
    """与 `evals.run.seed_corpus` 同口径：语料入库并建立 clause -> (key, articleNo) 映射。"""
    from app.schemas import PolicyDocumentCreate
    from app.services.policy import create_policy_document

    mapping = {}
    for raw in documents:
        request = PolicyDocumentCreate.model_validate(raw)
        document = create_policy_document(
            db, title=request.title, content=request.content, doc_number=request.docNumber,
            issuing_authority=request.issuingAuthority, status=request.status,
            industry_tags=request.industryTags, publish_date=request.publishDate,
            effective_date=request.effectiveDate, expiry_date=request.expiryDate,
            region=request.region, policy_version=request.policyVersion,
        )
        for clause in document.clauses:
            mapping[clause.id] = (raw.get("key", request.title), clause.article_no)
    return mapping


def main():
    parser = argparse.ArgumentParser(description="图谱增益对比（G1 验收方式）")
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--output", default="evals/reports/graph-gain.json")
    parser.add_argument("--require-gain", action="store_true", help="无增益时返回非零退出码（上线门禁）")
    args = parser.parse_args()
    report = evaluate(args.mode)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    decision = report["decision"]
    print(json.dumps({
        "promoted": decision["promoted"], "output": str(target), **decision["summary_line"],
    }, ensure_ascii=False))
    raise SystemExit(1 if (args.require_gain and not decision["promoted"]) else 0)


if __name__ == "__main__":
    main()
