"""G1 图谱最小闭环回归：Schema 准入、对齐去重、落图幂等、多跳遍历、社区摘要、RRF 接入与降级。

口径：抽取全部走规则化通道（`allow_llm=False` 或关掉模型 Key），只证明工程行为可回归；
真实抽取质量与"是否值得上线"的结论见 `evals.graph_gain` 的报告，不在测试里冒充。
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import models as business_models  # noqa: F401  注册业务表供 create_all
from app.agent import models as agent_models  # noqa: F401
from app.agent import platform_models  # noqa: F401
from app.config import settings
from app.db import Base
from app.kg import models as kg_models  # noqa: F401
from app.kg.align import EntityAligner, canonical_key, name_similarity
from app.kg.build import build_graph
from app.kg.community import build_communities, detect_communities
from app.kg.extract import extract_clause
from app.kg.models import KGEntity
from app.kg.retrieval import graph_search
from app.kg.schema import validate_extraction
from app.kg.store import GraphStore
from app.services.policy import create_policy_document, search_policy_clauses

BASE_DOC = "测试数据安全管理条例"
IMPL_DOC = "测试数据安全实施细则"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture()
def offline(monkeypatch):
    """离线口径：不调用任何付费模型，向量与精排都走确定性兜底。"""
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    monkeypatch.setattr(settings, "rerank_url", "")
    monkeypatch.setattr(settings, "rerank_api_key", "")
    monkeypatch.setattr(settings, "rerank_local_model", "")
    return settings


def _seed_documents(db):
    base = create_policy_document(
        db, title=BASE_DOC,
        content="第一条 数据处理企业应建立访问权限审批制度。\n第二条 企业应当每年开展一次权限审计。",
        doc_number="TEST-DSL-BASE", issuing_authority="测试数据局", region="全国", industry_tags=["科技"],
    )
    impl = create_policy_document(
        db, title=IMPL_DOC,
        content="第一条 本细则依据《测试数据安全管理条例》制定。\n第二条 企业向第三方提供个人信息前应取得单独同意。",
        doc_number="TEST-DSL-IMPL", issuing_authority="测试数据局", region="全国", industry_tags=["科技"],
    )
    return base, impl


# ---------- Schema 准入 ----------

def test_schema_rejects_free_text_and_dangling_relations():
    result = validate_extraction({
        "entities": [
            {"name": BASE_DOC, "type": "Policy"},
            {"name": "测试数据局", "type": "Authority"},
            {"name": "某神秘事物", "type": "自由文本"},
        ],
        "relations": [
            {"head": "测试数据局", "tail": BASE_DOC, "type": "issues"},
            {"head": "测试数据局", "tail": "某神秘事物", "type": "issues"},
            {"head": "测试数据局", "tail": BASE_DOC, "type": "自造关系"},
        ],
    })
    assert [entity["name"] for entity in result["entities"]] == [BASE_DOC, "测试数据局"]
    assert len(result["relations"]) == 1
    reasons = {item["reason"] for item in result["rejected"]}
    assert {"entity_type_not_in_schema", "dangling_endpoint", "relation_type_not_in_schema"} <= reasons


def test_schema_rejects_type_mismatch_and_merges_duplicates():
    result = validate_extraction({
        "entities": [
            {"name": "科技", "type": "Industry"},
            {"name": "测试数据局", "type": "Authority"},
            {"name": "测试数据局（以下简称数据局）", "type": "Authority", "aliases": ["数据局"]},
        ],
        "relations": [{"head": "科技", "tail": "测试数据局", "type": "issues"}],
    })
    assert [entity["name"] for entity in result["entities"]] == ["科技", "测试数据局"]
    assert result["entities"][1]["aliases"] == ["数据局"]
    assert result["relations"] == []
    reasons = [item["reason"] for item in result["rejected"]]
    assert "duplicate_name_merged" in reasons
    assert "endpoint_type_mismatch" in reasons


# ---------- 实体对齐 ----------

def test_alignment_normalizes_aliases_and_keeps_short_names_separate():
    assert canonical_key("测试科技局（以下简称科技局）") == canonical_key("测试科技局")
    assert canonical_key("市监局") == canonical_key("市场监督管理局")
    assert name_similarity("科技局", "测试科技局") < settings.kg_alignment_threshold
    aligner = EntityAligner(threshold=settings.kg_alignment_threshold)
    aligner.resolve("Policy", BASE_DOC)
    assert aligner.resolve("Policy", f"{BASE_DOC}（试行）").reason == "exact"
    # 不同类型各自建索引：同名实体不会被跨类型并成一个节点。
    assert aligner.resolve("Authority", BASE_DOC).reason == "new"


# ---------- 落图幂等 ----------

def test_upsert_is_idempotent_and_replaces_edges_for_same_source(db, offline):
    extraction = extract_clause(
        "第一条 数据处理企业应建立访问权限审批制度。",
        context={
            "title": BASE_DOC, "authority": "测试数据局", "region": "全国",
            "industry": ["科技"], "doc_id": 1, "article_no": "第一条", "parent_key": "article:0",
        },
        clause_key="policy:1#第一条#article:0", allow_llm=False,
    )
    assert extraction["backend"] == "rule"
    store = GraphStore(db, tenant_id="default")
    first = store.upsert(
        extraction, tenant_id="default", classification="public", source_key="policy:1#第一条#article:0",
    )
    assert first["entitiesNew"] > 0 and first["relationsNew"] > 0
    second = store.upsert(
        extraction, tenant_id="default", classification="public", source_key="policy:1#第一条#article:0",
    )
    assert second["relationsNew"] == first["relationsNew"]
    assert second["relationsReplaced"] == first["relationsNew"]
    assert store.stats("default")["relations"] == first["relationsNew"]


def test_rule_extraction_emits_based_on_relation(db, offline):
    extraction = extract_clause(
        "第一条 本细则依据《测试数据安全管理条例》制定。",
        context={"title": IMPL_DOC, "authority": "测试数据局"},
        clause_key="policy:2#第一条#", allow_llm=False,
    )
    assert any(
        relation["type"] == "basedOn" and relation["tail"] == BASE_DOC
        for relation in extraction["relations"]
    )


# ---------- 多跳遍历与图召回 ----------

def test_build_and_graph_search_reaches_upper_reference(db, offline):
    base, _ = _seed_documents(db)
    result = build_graph(db, tenant_id="default", communities=True)
    assert result["clauses"] == 4
    assert result["backends"] == {"rule": 4}
    assert result["graph"]["entities"] > 0 and result["graph"]["relations"] > 0

    out = graph_search(db, f"{IMPL_DOC}的上位依据是哪一份文件？", limit=6)
    assert out["degraded"] is False
    assert out["hits"], "图遍历应命中被引用条例的条款"
    base_hits = [hit for hit in out["hits"] if hit["docId"] == base.id]
    assert base_hits, "图遍历应经 basedOn 走到被引用的条例条款"
    hit = base_hits[0]
    assert hit["articleNo"] == "第一条"
    labels = [step["label"] for step in hit["path"]]
    assert len(hit["path"]) >= 2 and "依据" in labels
    assert out["communities"], "社区摘要应可作为全局性问题的入口"


def test_graph_source_adds_candidates_vector_cannot_reach(db, offline):
    base, _ = _seed_documents(db)
    build_graph(db, tenant_id="default", communities=False)
    question = f"{IMPL_DOC}的上位依据是哪一份文件？"
    dense_only = search_policy_clauses(db, question, limit=6, fusion_sources=("dense",))
    with_graph = search_policy_clauses(
        db, question, limit=6, fusion_sources=("lexical", "dense", "graph"),
    )
    assert not [row for row in dense_only if row["clause"].doc_id == base.id], "纯向量不应凭词面召回被引用条例"
    assert [row for row in with_graph if row["clause"].doc_id == base.id], "图这一路应把关系可达条款补进候选"
    assert with_graph[0]["retrieval"]["graph"]["hits"] > 0


def test_graph_failure_degrades_without_breaking_retrieval(db, offline):
    _seed_documents(db)
    build_graph(db, tenant_id="default", communities=False)
    with patch("app.kg.retrieval.graph_search", side_effect=RuntimeError("graph down")):
        hits = search_policy_clauses(
            db, "数据处理企业的权限审批要求？", limit=6,
            fusion_sources=("lexical", "dense", "graph"),
        )
    assert hits, "图谱失败不能让检索整体失败"
    assert hits[0]["retrieval"]["graph"]["degraded"] is True
    assert hits[0]["retrieval"]["fusionSources"] == ["lexical", "dense", "graph"]


# ---------- 租户与密级 ----------

def test_graph_search_hides_internal_entities_from_public_callers(db, offline):
    store = GraphStore(db, tenant_id="default")
    store.upsert(
        {"entities": [{"name": "内部涉密主体", "type": "Enterprise"}], "relations": [], "rejected": []},
        tenant_id="default", classification="internal", source_key="internal:1",
    )
    graph = store.load(tenant_id="default")
    assert all(data["name"] != "内部涉密主体" for _, data in graph.nodes(data=True))
    out = graph_search(db, "内部涉密主体", limit=5)
    assert all(hit["name"] != "内部涉密主体" for hit in out["hits"])


# ---------- 社区摘要 ----------

def test_communities_are_deterministic_and_linked(db, offline):
    _seed_documents(db)
    result = build_graph(db, tenant_id="default", communities=True)
    assert result["communities"]["written"] >= 1
    store = GraphStore(db, tenant_id="default")
    graph = store.load(tenant_id="default")
    first = detect_communities(graph, min_size=2)
    assert [row["nodes"] for row in detect_communities(graph, min_size=2)] == [row["nodes"] for row in first]
    build_communities(db, graph, tenant_id="default", classification="public")
    assert store.stats("default")["communities"] == result["communities"]["written"]
    assert db.query(KGEntity).filter(KGEntity.community_id.isnot(None)).count() > 0


# ---------- 增益判定口径 ----------

def test_gain_decision_requires_positive_gain():
    from evals.graph_gain import decide

    def variants(vector_recall, vector_mrr, graph_recall, graph_mrr):
        def summary(recall, mrr):
            return {
                "recall_at_k": recall, "mrr": mrr, "ndcg_at_k": 0.0,
                "cases": 8, "degraded_graph_cases": 0,
            }
        return {
            "dense_only": {"summary": summary(vector_recall, vector_mrr)},
            "lexical_dense": {"summary": summary(1.0, 0.4)},
            "lexical_dense_graph": {"summary": summary(graph_recall, graph_mrr)},
        }

    assert decide(variants(0.0, 0.0, 1.0, 0.42))["promoted"] is True
    assert decide(variants(1.0, 0.4, 1.0, 0.4))["promoted"] is False, "持平即不上线"
    assert decide(variants(1.0, 0.4, 1.0, 0.5))["promoted"] is True
