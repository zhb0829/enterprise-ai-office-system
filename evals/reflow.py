"""线上回流测试集（G2 闭环后半段）：badcase → 人工标注 → 晋级真实语料集。

流程固定为三步，未标注内容不允许被当成测试集：

```powershell
.venv\\Scripts\\python.exe -m evals.reflow draft --from-db --output evals/datasets/reflow/pending-2026-10-25.json
.venv\\Scripts\\python.exe -m evals.reflow validate evals/datasets/reflow/pending-2026-10-25.json
.venv\\Scripts\\python.exe -m evals.reflow promote evals/datasets/reflow/pending-2026-10-25.json `
    --output evals/datasets/reflow/real-2026-10-25.json
```

标注要求（双人复核后由本人填写）：`labeled`、`labeledBy`、`labeledAt` 必须齐全，
且 `expected` / `answerContains` / `refusal` 至少有一项有效；`refusal: true` 时不得再填期望条款。
晋级产物 `synthetic: false`，由 `evals.run --dataset reflow` 评测。
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

MIN_CONTENT = 20
# 检索上下文字段：合成集使用了 asOf/region/policyName 等，回流集若丢弃会让时效、地区类
# 用例在评测中系统性失败，因此标注时可以回填并保留。
CONTEXT_FIELDS = ("asOf", "region", "policyName", "industry", "authority")


def clause_index(corpus):
    """按语料切分结果建立 key → 可命中 article_no 集合，防止"校验通过但评测必失败"。"""
    from app.services.policy import split_policy_clauses
    index = {}
    for document in corpus or []:
        key = str(document.get("key", ""))
        bucket = index.setdefault(key, set())
        for clause in split_policy_clauses(str(document.get("content") or "")):
            bucket.add(str(clause.get("article_no", "")))
    return index


def load_badcases(path):
    rows = []
    # 标注与导出文件常由 Windows 工具编辑，允许带 BOM。
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _corpus_document(title, clauses):
    """把 badcase 引用到的条款正文按条拼接成可切分的语料文档。"""
    bodies = []
    for article_no in sorted(clauses, key=lambda value: (len(str(value)), str(value))):
        citation = clauses[article_no]
        body = str(citation.get("excerpt") or "").strip()
        article_no = str(article_no or "").strip()
        if article_no and not body.startswith(article_no):
            body = f"{article_no} {body}".strip()
        if body:
            bodies.append(body)
    content = "\n".join(bodies)
    if len(content) < MIN_CONTENT:
        content = f"{title}\n{content}\n（回流样本正文过短，标注时请回填原始政策文件条款）"
    return {
        "key": title,
        "title": title,
        "content": content,
        "docNumber": "",
        "issuingAuthority": "",
        "level": "其他",
        "status": "现行有效",
        "industryTags": [],
        "sourceUrl": next(
            (str(item.get("sourceUrl") or "") for item in clauses.values() if item.get("sourceUrl")), "",
        ),
    }


def draft(cases, label=None):
    """由 badcase 生成待人工标注数据集；没有问题文本的条目直接丢弃并记账。"""
    label = label or date.today().isoformat()
    corpus = {}
    rows, skipped = [], 0
    for case in cases:
        question = str(case.get("question") or "").strip()
        if not question:
            skipped += 1
            continue
        candidates = []
        for citation in case.get("citations") or []:
            if not isinstance(citation, dict):
                continue
            title = str(citation.get("docTitle") or citation.get("key") or "").strip()
            if not title:
                continue
            article_no = str(citation.get("articleNo") or "").strip()
            corpus.setdefault(title, {"title": title, "clauses": {}})
            corpus[title]["clauses"].setdefault(article_no, citation)
            candidates.append({"key": title, "articleNo": article_no, "docTitle": title})
        rows.append({
            "id": str(case.get("case_id") or f"bc-{len(rows) + 1:04d}"),
            "question": question,
            "candidateClauses": candidates,
            "expected": [],
            "answerContains": [],
            "refusal": None,
            **{key: "" for key in CONTEXT_FIELDS},
            "labeled": False,
            "labeledBy": "",
            "labeledAt": "",
            "reviewedBy": "",
            "note": "",
            "labels": case.get("labels") or [],
            "sourceRun": case.get("runId") or "",
        })
    return {
        "dataset_version": f"pending-{label}",
        "state": "pending-labeling",
        "synthetic": False,
        "labeled_by": "",
        "labeled_at": "",
        "source": "production-reflow",
        "corpus": [_corpus_document(title, entry["clauses"]) for title, entry in corpus.items()],
        "cases": rows,
        "intake": {"badcases": len(cases), "usable": len(rows), "skipped_without_question": skipped},
    }


def validate(dataset):
    """返回错误列表；空列表表示可以晋级。"""
    errors = []
    corpus_keys = {str(document.get("key", "")) for document in dataset.get("corpus") or []}
    index = clause_index(dataset.get("corpus") or [])
    if not corpus_keys:
        errors.append("corpus 为空：回流集必须带真实条款正文，不能用空语料占位")
    if not dataset.get("labeled_by"):
        errors.append("labeled_by 缺失：需填写标注人（建议双人复核，复核人写入 reviewedBy）")
    if not dataset.get("labeled_at"):
        errors.append("labeled_at 缺失：需填写标注日期")
    cases = dataset.get("cases") or []
    if not cases:
        errors.append("cases 为空：没有可回归的真实用例")
    for case in cases:
        case_id = case.get("id", "?")
        if not case.get("labeled"):
            errors.append(f"{case_id}: 未标注（labeled 必须为 true）")
            continue
        if not case.get("labeledBy") or not case.get("labeledAt"):
            errors.append(f"{case_id}: 缺少 labeledBy / labeledAt")
        refusal = case.get("refusal")
        expected = case.get("expected") or []
        contains = [item for item in (case.get("answerContains") or []) if str(item).strip()]
        if refusal is None and not expected and not contains:
            errors.append(f"{case_id}: expected / answerContains / refusal 至少填写一项")
        if refusal:
            if expected:
                errors.append(f"{case_id}: 标注为拒答时不得再填 expected")
        if refusal is None and not expected:
            errors.append(f"{case_id}: 未标注拒答时必须给出 expected 条款")
        for item in expected:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                errors.append(f"{case_id}: expected 项必须是 [key, articleNo] 二元组")
                continue
            key, article_no = str(item[0]), str(item[1])
            if key not in corpus_keys:
                errors.append(f"{case_id}: expected 引用的语料 key 不存在：{key}")
            elif article_no not in index.get(key, set()):
                errors.append(
                    f"{case_id}: expected 条款 {key} {article_no} 在语料切分后不存在，评测必然失败"
                )
        if not str(case.get("question") or "").strip():
            errors.append(f"{case_id}: question 为空")
    return errors


def promote(dataset, label=None):
    """校验通过后生成可回归的真实语料数据集；校验失败直接抛错，不产出半成品。"""
    errors = validate(dataset)
    if errors:
        raise ValueError("回流集校验未通过：\n- " + "\n- ".join(errors))
    label = label or str(dataset.get("labeled_at") or date.today().isoformat())
    cases = []
    for case in dataset["cases"]:
        context = {
            key: case[key] for key in CONTEXT_FIELDS
            if case.get(key) not in (None, "", [], {})
        }
        cases.append({
            "id": case["id"],
            "question": case["question"],
            "expected": [list(item) for item in case.get("expected") or []],
            "answerContains": case.get("answerContains") or [],
            "refusal": bool(case.get("refusal")) if case.get("refusal") is not None else False,
            **context,
            "labeled": True,
            "labeledBy": case.get("labeledBy", ""),
            "labeledAt": case.get("labeledAt", ""),
            "reviewedBy": case.get("reviewedBy", ""),
            "labels": case.get("labels") or [],
            "sourceRun": case.get("sourceRun", ""),
        })
    return {
        "dataset_version": f"production-reflow-{label}",
        "state": "labeled",
        "synthetic": False,
        "source": "production-reflow",
        "labeled_by": dataset.get("labeled_by", ""),
        "labeled_at": dataset.get("labeled_at", ""),
        "corpus": dataset["corpus"],
        "cases": cases,
    }


def write_dataset(dataset, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


def _load_source(args):
    if args.from_db:
        from .badcase import collect
        from app import db as app_db
        with app_db.SessionLocal() as session:
            return collect(session, tenant=args.tenant, since_days=args.since_days, limit=args.limit)
    if not args.badcases:
        raise SystemExit("draft 需要 --badcases <jsonl> 或 --from-db")
    return load_badcases(args.badcases)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    draft_parser = sub.add_parser("draft", help="由 badcase 生成待标注数据集")
    draft_parser.add_argument("--badcases", default="")
    draft_parser.add_argument("--from-db", action="store_true")
    draft_parser.add_argument("--tenant", default="")
    draft_parser.add_argument("--since-days", type=int, default=None)
    draft_parser.add_argument("--limit", type=int, default=2000)
    draft_parser.add_argument("--label", default="")
    draft_parser.add_argument("--output", default=f"evals/datasets/reflow/pending-{date.today().isoformat()}.json")

    validate_parser = sub.add_parser("validate", help="校验标注完整性")
    validate_parser.add_argument("dataset")

    promote_parser = sub.add_parser("promote", help="校验并晋级为真实语料测试集")
    promote_parser.add_argument("dataset")
    promote_parser.add_argument("--label", default="")
    promote_parser.add_argument("--output", default="")

    args = parser.parse_args()
    if args.command == "draft":
        dataset = draft(_load_source(args), args.label or None)
        print(json.dumps({
            "output": write_dataset(dataset, args.output),
            "tenantScope": args.tenant or "all-tenants",
            **dataset["intake"],
        }, ensure_ascii=False))
        return
    if args.command == "validate":
        dataset = load_json(args.dataset)
        errors = validate(dataset)
        print(json.dumps({"dataset": args.dataset, "cases": len(dataset.get("cases") or []), "errors": errors}, ensure_ascii=False))
        raise SystemExit(0 if not errors else 1)
    dataset = load_json(args.dataset)
    try:
        real = promote(dataset, args.label or None)
    except ValueError as exc:
        print(json.dumps({"dataset": args.dataset, "errors": str(exc).splitlines()[1:]}, ensure_ascii=False))
        raise SystemExit(1) from exc
    output = args.output or f"evals/datasets/reflow/real-{dataset.get('labeled_at') or date.today().isoformat()}.json"
    print(json.dumps({"output": write_dataset(real, output), "cases": len(real["cases"]), "synthetic": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()