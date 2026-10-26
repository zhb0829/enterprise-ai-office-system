"""指标劣化门禁（G2 验收方式）：每次改切片、换嵌入模型、动精排权重先跑全量回归。

规则：

- 数据集摘要、来源、模式与用例数必须与基线一致；摘要覆盖语料与用例内容，
  等量替换用例同样会被阻断，刷新基线只能由人工显式执行。
- 通过率必须为 1，沿用 `evals.run` 的退出码口径。
- 只对方向明确的指标做单调门禁：
  `recall_at_k / mrr / ndcg_at_k / answer_accuracy / answer_completeness /
  citation_precision / citation_traceability` 不得下降，`fallback_rate` 不得上升。
- 基线有值而本次缺失（NULL）视为劣化，不允许用"清空标注让指标消失"绕过门禁。
- 拒答率与延迟只报告不做方向门禁：合规场景拒绝回答不算劣化，延迟受机器与并发影响。
- 基线或报告缺失一律失败，不静默放行。

```powershell
.venv\\Scripts\\python.exe -m evals.run --mode offline --output evals/reports/ci.json
.venv\\Scripts\\python.exe -m evals.gate --report evals/reports/ci.json --baseline evals/baselines/offline.json
# 人工批准后刷新；指标下调会被拒绝，除非显式 --force 并留痕
.venv\\Scripts\\python.exe -m evals.gate --report evals/reports/ci.json --update-baseline `
    --approver 张三 --reason "切片策略 v3 上线，已复核全部用例"
```
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

EPSILON = 1e-9

DIRECTIONS = {
    ("retrieval", "recall_at_k"): "higher",
    ("retrieval", "mrr"): "higher",
    ("retrieval", "ndcg_at_k"): "higher",
    ("generation", "answer_accuracy"): "higher",
    ("generation", "answer_completeness"): "higher",
    ("citation", "citation_precision"): "higher",
    ("citation", "citation_traceability"): "higher",
    ("experience", "fallback_rate"): "lower",
}
REPORTED_ONLY = (
    ("citation", "refusal_rate"),
    ("experience", "latency_p50_ms"),
    ("experience", "latency_p95_ms"),
)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(payload, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def metric(report, layer, name):
    value = ((report.get("layers") or {}).get(layer) or {}).get(name)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def baseline_from_report(report, *, forced=False, approver="", reason=""):
    note = "由 evals.gate --update-baseline 人工刷新；CI 只允许持平或提升。"
    if forced:
        note = (
            f"人工 --force 刷新（超出单调门禁）：审批人={approver or '未填写'}；"
            f"原因={reason or '未填写'}。{note}"
        )
    return {
        "generated_at": report.get("generated_at", ""),
        "dataset_version": report.get("dataset_version", ""),
        "dataset_source": report.get("dataset_source", ""),
        "dataset_digest": report.get("dataset_digest", ""),
        "synthetic": report.get("synthetic"),
        "mode": report.get("mode", ""),
        "summary": report.get("summary", {}),
        "layers": report.get("layers", {}),
        "note": note,
    }


def _identity_failures(current, baseline):
    failures = []
    if not (current.get("layers") or {}):
        failures.append({"check": "layers", "reason": "当前报告缺少四层结构"})
    for field, label in (("mode", "运行模式"), ("dataset_source", "数据集来源")):
        if current.get(field) != baseline.get(field):
            failures.append({
                "check": field,
                "reason": f"{label}变化：{baseline.get(field)} -> {current.get(field)}",
            })
    if current.get("synthetic") != baseline.get("synthetic"):
        failures.append({
            "check": "synthetic",
            "reason": f"数据集性质变化：{baseline.get('synthetic')} -> {current.get('synthetic')}",
        })
    if baseline.get("dataset_digest") and current.get("dataset_digest") != baseline.get("dataset_digest"):
        failures.append({
            "check": "dataset_digest",
            "reason": "语料或用例内容变化（摘要不一致）；等量替换用例同样被阻断，需人工刷新基线",
        })
    if current.get("dataset_version") != baseline.get("dataset_version"):
        failures.append({
            "check": "dataset_version",
            "reason": f"数据集变化：{baseline.get('dataset_version')} -> {current.get('dataset_version')}；需人工刷新基线",
        })
    current_total = (current.get("summary") or {}).get("total")
    baseline_total = (baseline.get("summary") or {}).get("total")
    if current_total != baseline_total:
        failures.append({
            "check": "cases",
            "reason": f"用例数变化：{baseline_total} -> {current_total}；需人工刷新基线",
        })
    pass_rate = (current.get("summary") or {}).get("pass_rate")
    if pass_rate != 1:
        failures.append({"check": "pass_rate", "reason": f"通过率 {pass_rate} 未达到 1"})
    return failures


def compare(current, baseline, tolerance=0.0):
    failures = _identity_failures(current, baseline)
    comparisons = []
    for (layer, name), direction in DIRECTIONS.items():
        old, new = metric(baseline, layer, name), metric(current, layer, name)
        row = {"layer": layer, "metric": name, "direction": direction, "baseline": old, "current": new}
        if old is None and new is None:
            row.update(status="skipped", reason="基线与本次都缺少该指标样本")
        elif new is None:
            # 基线有值而本次消失，是"清空标注让指标消失"的绕过路径，直接判定劣化。
            row.update(status="regressed", reason="基线有值而本次缺失（NULL 视为劣化）")
        elif old is None:
            row.update(status="ok", reason="基线无样本，本次首次取得数值")
        else:
            delta = new - old
            row["delta"] = round(delta, 6)
            regressed = (delta < -tolerance - EPSILON) if direction == "higher" else (delta > tolerance + EPSILON)
            row["status"] = "regressed" if regressed else "ok"
            if regressed:
                row["reason"] = "指标劣化，阻断发布"
        comparisons.append(row)
        if row["status"] == "regressed":
            failures.append(row)

    reported = []
    for layer, name in REPORTED_ONLY:
        old, new = metric(baseline, layer, name), metric(current, layer, name)
        reported.append({
            "layer": layer, "metric": name, "baseline": old, "current": new,
            "delta": round(new - old, 6) if isinstance(old, (int, float)) and isinstance(new, (int, float)) else None,
            "note": "仅报告，不做方向门禁",
        })

    return {
        "generated_at": datetime.now().isoformat(),
        "tolerance": tolerance,
        "passed": not failures,
        "failures": failures,
        "comparisons": comparisons,
        "reported_only": reported,
        "baseline_generated_at": baseline.get("generated_at", ""),
    }


def baseline_regressions(current, previous):
    """刷新基线前的下调检查：任何门禁指标变差或消失都要人工确认。"""
    problems = []
    for (layer, name), direction in DIRECTIONS.items():
        old, new = metric(previous, layer, name), metric(current, layer, name)
        if old is None:
            continue
        if new is None:
            problems.append(f"{layer}.{name} 由 {old} 变为缺失（NULL）")
        elif direction == "higher" and new < old - EPSILON:
            problems.append(f"{layer}.{name} 下调 {old} -> {new}")
        elif direction == "lower" and new > old + EPSILON:
            problems.append(f"{layer}.{name} 上调 {old} -> {new}")
    if previous.get("dataset_digest") and previous.get("dataset_digest") != current.get("dataset_digest"):
        problems.append("数据集摘要变化（语料或用例内容已改动）")
    return problems


def update_baseline(current, baseline_path, *, force=False, approver="", reason=""):
    if (current.get("summary") or {}).get("pass_rate") != 1:
        raise SystemExit("拒绝刷新基线：当前报告通过率未达到 1，先修好再谈基线")
    problems = []
    path = Path(baseline_path)
    if path.exists():
        problems = baseline_regressions(current, load_json(path))
    if problems and not force:
        raise SystemExit(
            "拒绝刷新基线：存在指标下调或数据集变化，需人工确认后加 --force 并填写 --approver/--reason 留痕：\n- "
            + "\n- ".join(problems)
        )
    payload = baseline_from_report(current, forced=bool(problems), approver=approver, reason=reason)
    return write_json(payload, baseline_path), problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="evals/reports/ci.json")
    parser.add_argument("--baseline", default="evals/baselines/offline.json")
    parser.add_argument("--output", default="evals/reports/gate.json")
    parser.add_argument("--tolerance", type=float, default=0.0)
    parser.add_argument("--update-baseline", action="store_true", help="人工批准后刷新基线")
    parser.add_argument("--force", action="store_true", help="确认强制刷新（记录审批人与原因）")
    parser.add_argument("--approver", default="", help="强制刷新时的审批人")
    parser.add_argument("--reason", default="", help="强制刷新时的原因")
    args = parser.parse_args()

    report_path, baseline_path = Path(args.report), Path(args.baseline)
    if not report_path.exists():
        raise SystemExit(f"门禁失败：找不到评测报告 {report_path}；请先执行 evals.run")
    current = load_json(report_path)

    if args.update_baseline:
        path, problems = update_baseline(
            current, baseline_path, force=args.force,
            approver=args.approver, reason=args.reason,
        )
        print(json.dumps({
            "updated": path, "dataset_version": current.get("dataset_version"),
            "forced": bool(problems), "overridden": problems,
        }, ensure_ascii=False))
        return

    if not baseline_path.exists():
        raise SystemExit(f"门禁失败：找不到基线 {baseline_path}；需人工执行 --update-baseline 并提交")
    baseline = load_json(baseline_path)
    result = compare(current, baseline, args.tolerance)
    result["report"] = str(report_path)
    result["baseline"] = str(baseline_path)
    write_json(result, args.output)
    print(json.dumps({
        "passed": result["passed"],
        "failures": result["failures"],
        "output": args.output,
    }, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()