"""构图入口（G1）：把政策条款抽取成图，并生成社区摘要。

```powershell
# 为 default 租户下全部已完成政策文档构图，并生成社区摘要
.venv\\Scripts\\python.exe -m app.kg.build --tenant default
# 只构图，不写社区摘要
.venv\\Scripts\\python.exe -m app.kg.build --no-communities
```

三条纪律：

- **幂等**：节点按「类型 + 归一键」合并，关系按 `relation_key` 唯一，重复构图不产生重复边。
- **有预算**：一个任务最多调用 `kg_extract_budget_per_job` 次抽取模型，超出后自动改用规则化
  通道并在统计里记 `llmBudgetExhausted`，不做无限重试。
- **可审计**：返回条款数、抽取后端分布、Schema 拒绝数，便于判断"图为什么这么稀"。
"""
from __future__ import annotations

import argparse
import json

from ..config import settings
from ..agent.runtime_flags import disabled as flag_disabled
from ..models import PolicyClause, PolicyDocument
from ..services.llm import LLMClient
from .community import build_communities
from .extract import extract_clause
from .retrieval import clause_key_for
from .store import GraphStore

_STAT_KEYS = (
    "entitiesNew", "entitiesMerged", "entitiesUpdated",
    "relationsNew", "relationsSkipped", "relationsReplaced", "rejected",
)


def clause_context(clause, document) -> dict:
    """条款的构图上下文：结构化元数据 + 可回溯到条款的键。"""
    meta = clause.meta or {}
    parent_key = meta.get("parent_key", "")
    return {
        "title": document.title,
        "authority": document.issuing_authority,
        "region": document.region,
        "industry": list(document.industry_tags or []),
        "doc_number": document.doc_number,
        "article_no": clause.article_no,
        "doc_id": document.id,
        "clause_id": clause.id,
        "parent_key": parent_key,
        "clause_key": clause_key_for(
            doc_id=document.id, article_no=clause.article_no, parent_key=parent_key,
        ),
    }


def iter_clauses(db, *, document_ids=None, limit=None):
    query = (
        db.query(PolicyClause, PolicyDocument)
        .join(PolicyDocument, PolicyClause.doc_id == PolicyDocument.id)
        .filter(PolicyDocument.parse_status == "已完成")
        .order_by(PolicyClause.doc_id, PolicyClause.id)
    )
    if document_ids:
        query = query.filter(PolicyClause.doc_id.in_(list(document_ids)))
    rows = query.all()
    return rows[: int(limit)] if limit else rows


def build_graph(
    db,
    *,
    document_ids=None,
    tenant_id=None,
    classification: str = "public",
    llm: LLMClient | None = None,
    budget: int | None = None,
    limit: int | None = None,
    communities: bool = True,
    domain: str = "policy",
) -> dict:
    """抽取 → 对齐 → 落图 →（可选）社区摘要；返回可审计统计。"""
    tenant = tenant_id or "default"
    # G5：只有运维**显式关闭**图谱开关时才拒绝构图（构图会产生额外模型成本）；
    # 配置默认未启用图谱（KG_ENABLED=false）不影响 CLI 主动构图与离线评测。
    if flag_disabled("kg"):
        return {
            "tenantId": tenant, "skipped": True, "reason": "runtime-flag-kg-off",
            "clauses": 0, "documents": 0, "graph": GraphStore(db, domain=domain, tenant_id=tenant).stats(tenant),
        }
    llm = llm if llm is not None else LLMClient()
    remaining = int(budget if budget is not None else settings.kg_extract_budget_per_job)
    store = GraphStore(db, domain=domain, tenant_id=tenant)
    stats: dict = {
        "clauses": 0, "backends": {}, "llmCalls": 0, "llmBudgetExhausted": False,
        "documents": 0, **{key: 0 for key in _STAT_KEYS},
    }
    document_ids_seen: set[int] = set()
    for clause, document in iter_clauses(db, document_ids=document_ids, limit=limit):
        context = clause_context(clause, document)
        allow_llm = remaining > 0
        if not llm.is_mock:
            if allow_llm:
                remaining -= 1
                stats["llmCalls"] += 1
            else:
                stats["llmBudgetExhausted"] = True
        extraction = extract_clause(
            clause.content, context=context, clause_key=context["clause_key"],
            llm=llm, allow_llm=allow_llm,
        )
        stats["backends"][extraction["backend"]] = stats["backends"].get(extraction["backend"], 0) + 1
        upsert_stats = store.upsert(
            extraction, tenant_id=tenant, classification=classification, source_key=context["clause_key"],
        )
        for key in _STAT_KEYS:
            stats[key] += upsert_stats[key]
        stats["clauses"] += 1
        document_ids_seen.add(document.id)
    stats["documents"] = len(document_ids_seen)
    store.refresh_degrees(tenant)
    result = {"tenantId": tenant, **stats}
    if communities:
        graph = store.load(tenant_id=tenant)
        result["communities"] = build_communities(
            db, graph, tenant_id=tenant, classification=classification, domain=domain, llm=llm,
        )
    result["graph"] = store.stats(tenant)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="政策知识图谱构图（G1）")
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--document-id", type=int, action="append", dest="document_ids", default=None)
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少条款（0 表示不限）")
    parser.add_argument("--budget", type=int, default=0, help="本任务模型调用上限（0 表示用配置值）")
    parser.add_argument(
        "--classification", default="public",
        choices=["public", "internal", "confidential", "restricted"],
    )
    parser.add_argument("--no-communities", action="store_true")
    args = parser.parse_args(argv)
    from ..db import SessionLocal

    with SessionLocal() as db:
        result = build_graph(
            db, document_ids=args.document_ids, tenant_id=args.tenant,
            classification=args.classification, budget=args.budget or None,
            limit=args.limit or None, communities=not args.no_communities,
        )
        db.commit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
