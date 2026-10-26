"""离线回归评测：检索 / 生成 / 引用 / 体验四层报告（G2）。

数据集来源分两类，不可混同：

- `synthetic`：人工构造的工程回归集，只能证明工程行为可回归。
- `reflow`：线上回流真实语料 + 人工标注；评测前强制走 `evals.reflow.validate`，
  未标注内容不得进入测试集，目录为空也不退回合成集。

报告写入 `dataset_digest`（语料与用例的 sha256），由 `evals.gate` 比对，
防止"等量替换用例"绕过门禁。任一用例失败返回非零退出码。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import time
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from .metrics import (
    average,
    citation_metrics,
    experience_metrics,
    generation_metrics,
    retrieval_metrics,
    summarize,
)

DATASETS = Path(__file__).parent / "datasets"
REFLOW_DIR = DATASETS / "reflow"
DEFAULT_AS_OF = "2026-10-11"
SYNTHETIC_VERSION = "synthetic-p0-v1"
RETRIEVAL_KEYS = ("recall_at_k", "mrr", "ndcg_at_k")
GENERATION_KEYS = ("answer_accuracy", "answer_completeness")
CITATION_KEYS = ("citation_precision", "citation_traceability")
# 离线口径必须真正关掉付费模型：settings 是进程单例，只改环境变量不足以在库内调用时生效。
OFFLINE_SETTINGS = ("llm_api_key", "embedding_api_key", "rerank_url", "rerank_api_key", "rerank_local_model")


def load(name):
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))


def canonical_digest(documents, cases):
    """语料与用例的内容摘要：任何等量替换都会改变它，供门禁比对。"""
    payload = json.dumps({"documents": documents, "cases": cases}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_reflow():
    """读取已晋级的真实语料回流集；缺文件或标注校验不通过时明确失败。"""
    paths = sorted(glob.glob(str(REFLOW_DIR / "real-*.json")))
    if not paths:
        raise FileNotFoundError(
            f"未找到已晋级回流数据集 {REFLOW_DIR}/real-*.json；请先用 evals.reflow 完成"
            "人工标注并晋级，不要用合成样本替代真实语料验收。"
        )
    from .reflow import validate
    payloads, problems = [], []
    for path in paths:
        name = Path(path).name
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        payloads.append((name, payload))
        if payload.get("synthetic") is not False:
            problems.append(f"{name}: synthetic 必须为 false")
        if payload.get("state") != "labeled":
            problems.append(f"{name}: state 必须为 labeled（待标注草稿不得评测）")
        problems.extend(f"{name}: {problem}" for problem in validate(payload))
    if problems:
        raise RuntimeError(
            "回流数据集未通过标注校验，拒绝评测（未标注内容不得进入测试集）：\n- "
            + "\n- ".join(problems)
        )
    documents = [document for _, payload in payloads for document in payload.get("corpus", [])]
    cases = [case for _, payload in payloads for case in payload.get("cases", [])]
    keys = [str(document.get("key", "")) for document in documents]
    if len(set(keys)) != len(keys):
        raise RuntimeError("回流集 corpus 存在重复 key，无法唯一定位期望条款")
    if any(not str(case.get("id") or "").strip() for case in cases):
        raise RuntimeError("回流集存在缺少 id 的用例")
    versions = sorted({
        str(payload.get("dataset_version", ""))
        for _, payload in payloads if payload.get("dataset_version")
    })
    return documents, cases, {
        "dataset_version": "+".join(versions) or "production-reflow",
        "synthetic": False,
        "source": "production-reflow",
        "digest": canonical_digest(documents, cases),
        "validation": {"passed": True, "checked_by": "evals.reflow.validate", "errors": []},
        "files": [name for name, _ in payloads],
        "labeled_by": sorted({
            str(payload.get("labeled_by", "")) for _, payload in payloads if payload.get("labeled_by")
        }),
        "labeled_at": sorted({
            str(payload.get("labeled_at", "")) for _, payload in payloads if payload.get("labeled_at")
        }),
    }


def seed_corpus(db, documents=None):
    from app.schemas import PolicyDocumentCreate
    from app.services.policy import create_policy_document
    documents = load("policy_corpus.json")["documents"] if documents is None else documents
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


def policy_cases(db, documents, raw_cases):
    """政策问答用例：同时产出检索、生成、引用与延迟数据。"""
    from app.schemas import PolicyQuery
    from app.services.policy import answer_policy
    mapping = seed_corpus(db, documents)
    cases = []
    for case in raw_cases:
        started = time.perf_counter()
        request = PolicyQuery.model_validate({"asOf": DEFAULT_AS_OF, **case})
        answer = answer_policy(db, request)
        latency_ms = (time.perf_counter() - started) * 1000
        retrieved = [mapping[citation["id"]] for citation in answer["clauses"]]
        metrics = retrieval_metrics(retrieved, [tuple(item) for item in case["expected"]])
        expected_refusal = bool(case.get("refusal", False))
        declined = not retrieved and answer["confidence"] == "none"
        generation = generation_metrics(answer["answer"], case.get("answerContains", []))
        # 只有本轮真的拒答才让引用层"不适用"；本应拒答却作答时必须暴露引用情况。
        citation = citation_metrics(answer["answer"], answer["clauses"], declined=declined)
        degraded = bool(answer.get("degraded"))
        passed = declined if expected_refusal else (
            metrics["recall_at_k"] == 1
            and all(fragment in answer["answer"] for fragment in case["answerContains"])
        )
        cases.append({
            "id": case["id"], "domain": "policy", "passed": passed, "latency_ms": latency_ms,
            **metrics, **generation, **citation,
            "degraded": degraded, "refused": declined, "expected_refusal": expected_refusal,
            "retrieved": retrieved,
        })
    return cases


def announcement_cases(llm):
    from app.services.factcheck import run_factcheck
    cases = []
    for case in load("announcements.json")["cases"]:
        started = time.perf_counter()
        elements = [
            {"verified_status": "来自用户输入", "source_ref": f"input:{index}", **item}
            for index, item in enumerate(case["facts"])
        ]
        report = run_factcheck(case["content"], elements, case.get("material", ""), llm)
        passed = bool(report) and all(item["status"] == case["status"] for item in report)
        if case["status"] == "一致":
            passed = passed and all(item.get("evidence") for item in report)
        cases.append({
            "id": case["id"], "domain": "announcement", "passed": passed,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "evidence_coverage": average([int(bool(item["evidence"])) for item in report]),
        })
    return cases


def meeting_cases():
    from app.meeting.generation import extract_insights
    cases = []
    for case in load("meetings.json")["cases"]:
        started = time.perf_counter()
        insights = extract_insights([{
            "id": 7, "parseStatus": "parsed", "parseResult": {"segments": [{
                "speaker": case["speaker"], "text": case["text"], "location": "第1段",
            }]},
        }])
        passed = bool(insights) and insights[0]["cardType"] == case["cardType"] and bool(insights[0]["sourceRef"])
        passed = passed and all(insights[0].get(key) == case[key] for key in ("actor", "expectedTime") if key in case)
        cases.append({
            "id": case["id"], "domain": "meeting", "passed": passed,
            "latency_ms": (time.perf_counter() - started) * 1000,
        })
    return cases


def samples(cases, keys):
    return {key: sum(1 for case in cases if case.get(key) is not None) for key in keys}


def build_layers(mode, cases):
    policy = [case for case in cases if case["domain"] == "policy"]
    retrieval = summarize(cases, RETRIEVAL_KEYS)
    generation = summarize(cases, GENERATION_KEYS)
    citation = summarize(cases, CITATION_KEYS)
    refusal_rate = average([int(case["refused"]) for case in policy]) if policy else None
    experience = experience_metrics(
        [case.get("latency_ms") for case in policy],
        [case.get("degraded") for case in policy],
    )
    live = mode == "live"
    return {
        "retrieval": {
            "applicable": True,
            "definition": "Recall@K / MRR / nDCG@K，沿用 evals/metrics.py",
            "samples": samples(cases, RETRIEVAL_KEYS),
            **retrieval,
        },
        "generation": {
            "applicable": True,
            "source": "llm" if live else "lexical-fallback",
            "application": "quality-acceptance" if live else "engineering-regression-only",
            "note": (
                "真实模型生成，可用于质量验收初审"
                if live else
                "离线强制关闭付费模型，答案由检索兜底产出；本层只证明管道能把标注片段组织进答案，不代表真实生成质量"
            ),
            "samples": samples(cases, GENERATION_KEYS),
            **generation,
        },
        "citation": {
            "applicable": True,
            "definition": "引用正确率=引用标记落在真实条款内的比例；可溯源率=条款带出处与正文的比例",
            "source": "llm-answer" if live else "fallback-answer",
            "application": "quality-acceptance" if live else "structural-regression-only",
            "note": (
                "真实模型答案的引用正确性与可溯源率"
                if live else
                "离线答案由检索兜底产出，引用标记与出处由管道结构保证，本层恒真，只证明引用结构未被破坏"
            ),
            "scope": "policy_qa",
            "samples": {**samples(cases, CITATION_KEYS), "refusal_rate": len(policy)},
            "refusal_rate": refusal_rate,
            **citation,
        },
        "experience": {
            "applicable": bool(policy),
            "scope": "policy_qa",
            **experience,
        },
    }


def build_report(mode, dataset, meta, cases, online=None):
    layers = build_layers(mode, cases)
    if online is not None:
        layers["citation"]["online"] = online
    synthetic = bool(meta.get("synthetic", True))
    report = {
        "dataset_version": meta.get("dataset_version", SYNTHETIC_VERSION),
        "dataset_source": "synthetic" if synthetic else "production-reflow",
        "dataset_digest": meta.get("digest", ""),
        "dataset_validation": meta.get("validation", {
            "passed": True, "checked_by": "n/a (engineering regression corpus)", "errors": [],
        }),
        "synthetic": synthetic,
        "mode": mode,
        "generated_at": datetime.now().isoformat(),
        "scope": (
            "Engineering regression; not real policy accuracy or production acceptance"
            if synthetic else
            "Production reflow corpus with human labels; covers the labeled questions only, "
            "not gateway, live models or full-chain acceptance"
        ),
        "cases": cases,
        "layers": layers,
        "summary": {
            "total": len(cases),
            "passed": sum(case["passed"] for case in cases),
            "pass_rate": average([int(case["passed"]) for case in cases]),
            **{metric: average([case.get(metric) for case in cases]) for metric in RETRIEVAL_KEYS},
        },
    }
    if meta.get("labeled_by"):
        report["labels"] = {"labeled_by": meta["labeled_by"], "labeled_at": meta.get("labeled_at", [])}
    if meta.get("files"):
        report["dataset_files"] = meta["files"]
    return report


def evaluate(mode="offline", dataset="synthetic", online_citation=False):
    with ExitStack() as stack:
        environment = {"APP_ENV": "test"}
        if mode == "offline":
            environment.update({name.upper(): "" for name in OFFLINE_SETTINGS})
        # 环境变量也要恢复：同进程重复调用不应污染其他测试或调用方。
        stack.enter_context(patch.dict(os.environ, environment))
        return _evaluate(mode, dataset, online_citation, stack)


def _evaluate(mode, dataset, online_citation, stack):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app import models as business_models  # noqa: F401  注册业务表，create_all 需要
    from app.agent import models as agent_models  # noqa: F401
    from app.agent import platform_models  # noqa: F401
    from app.db import Base
    from app.config import settings
    from app.services.llm import LLMClient
    if mode == "live" and not (settings.llm_api_key and settings.embedding_api_key and (settings.rerank_url or settings.rerank_local_model)):
        raise RuntimeError("Live eval requires LLM, Dense and semantic reranker configuration")
    if dataset == "reflow":
        documents, raw_cases, meta = load_reflow()
    else:
        documents = load("policy_corpus.json")["documents"]
        raw_cases = load("policy_qa.json")["cases"]
        meta = {
            "dataset_version": SYNTHETIC_VERSION, "synthetic": True,
            "digest": canonical_digest(documents, raw_cases),
        }
    if mode == "offline":
        for name in OFFLINE_SETTINGS:
            stack.enter_context(patch.object(settings, name, ""))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    cases = []
    with Session(engine) as db:
        cases.extend(policy_cases(db, documents, raw_cases))
        if dataset == "synthetic":
            cases.extend(announcement_cases(LLMClient()))
            cases.extend(meeting_cases())
    online = None
    if online_citation:
        from .citation_audit import summarize_database
        online = summarize_database()
    report = build_report(mode, dataset, meta, cases, online)
    engine.dispose()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument("--dataset", choices=["synthetic", "reflow"], default="synthetic")
    parser.add_argument("--output", default="evals/reports/latest.json")
    parser.add_argument(
        "--online-citation", action="store_true",
        help="附加业务库 AgentRun 与 verification_result 的引用层汇总（需可访问业务库）",
    )
    args = parser.parse_args()
    report = evaluate(args.mode, args.dataset, args.online_citation)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    raise SystemExit(0 if report["summary"]["pass_rate"] == 1 else 1)


if __name__ == "__main__":
    main()