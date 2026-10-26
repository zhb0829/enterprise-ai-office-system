"""评测四层口径（G2）。

- 检索层：Recall@K / MRR / nDCG@K（原有口径）。
- 生成层：答案准确率 / 完整性，只按人工标注的期望片段做字面核对。
- 引用层：引用正确率 / 可溯源率，只看引用标记是否指向真实条款、条款是否带可定位出处。
- 体验层：延迟分位 / 兜底率。

口径纪律：样本缺失记 null，不补零、不估算伪造；字面核对不得表述为语义质量结论。
"""
import math
import re
import statistics

CITATION_RE = re.compile(r"\[引用(\d+)\]")


def retrieval_metrics(retrieved, relevant, k=6):
    retrieved, relevant = retrieved[:k], set(relevant)
    if not relevant:
        return {"recall_at_k": None, "mrr": None, "ndcg_at_k": None}
    relevance = [int(item in relevant) for item in retrieved]
    recall = len(set(retrieved) & relevant) / len(relevant)
    mrr = next((1 / (index + 1) for index, hit in enumerate(relevance) if hit), 0)
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(relevance))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(k, len(relevant))))
    return {"recall_at_k": recall, "mrr": mrr, "ndcg_at_k": dcg / ideal}


def _field(item, name):
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def generation_metrics(answer, expected_fragments):
    """生成层：标注片段是否出现在答案中；无标注则为 null，不猜分。"""
    fragments = [str(item) for item in (expected_fragments or []) if str(item).strip()]
    if not fragments:
        return {"answer_accuracy": None, "answer_completeness": None}
    hits = sum(1 for fragment in fragments if fragment in (answer or ""))
    return {
        "answer_accuracy": 1.0 if hits == len(fragments) else 0.0,
        "answer_completeness": hits / len(fragments),
    }


def citation_metrics(answer, citations, *, declined=False):
    """引用层：引用正确率（标记落在真实条款内）与可溯源率（条款带出处与正文）。

    拒答、无条款时不适用，记 null；有条款却没有任何引用标记时正确率为 0。
    """
    citations = list(citations or [])
    if declined or not citations:
        return {"citation_precision": None, "citation_traceability": None}
    markers = [int(index) for index in CITATION_RE.findall(answer or "")]
    traceable = sum(
        1
        for item in citations
        if str(_field(item, "excerpt") or "").strip() and str(_field(item, "docTitle") or "").strip()
    )
    precision = (
        sum(1 for index in markers if 1 <= index <= len(citations)) / len(markers)
        if markers
        else 0.0
    )
    return {
        "citation_precision": precision,
        "citation_traceability": traceable / len(citations),
    }


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))]


def average(values):
    values = [value for value in values if value is not None]
    return statistics.mean(values) if values else None


def experience_metrics(latencies, fallback_flags):
    """体验层：延迟分位与兜底率；无样本记为 null。"""
    values = [float(value) for value in latencies if value is not None]
    flags = [bool(flag) for flag in fallback_flags if flag is not None]
    return {
        "latency_p50_ms": round(percentile(values, 0.5), 2) if values else None,
        "latency_p95_ms": round(percentile(values, 0.95), 2) if values else None,
        "fallback_rate": (sum(flags) / len(flags)) if flags else None,
        "latency_samples": len(values),
    }


def summarize(cases, keys):
    return {key: average([case.get(key) for case in cases]) for key in keys}