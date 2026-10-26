"""G9 LTR 学习排序：特征口径、训练门禁、RRF 保底与渐进替换。

口径（与 `app/agent/ltr.py` 一致）：

- 特征只有三个：向量相似度、图路径长度、文本匹配分；BM25 只在**本批候选内**归一化。
- 没有标注数据 / 单类标签 → 拒绝训练；样本外 AUC 不达标 → 不允许激活（409）。
- `off` / 模型缺失 / 异常都必须退回 RRF 原序，并标记 degraded；
  `shadow` 只算分不改线上顺序；`blend` 才改顺序，且 RRF 分始终保留。
"""
from __future__ import annotations

import random
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import main as app_main
from app.agent import ltr, runtime_flags
from app.agent.ltr import RankingModel, TrainingSample
from app.agent.platform_models import GovernanceAudit
from app.config import settings
from app.schemas import PolicyQuery
from app.services.policy import answer_policy, create_policy_document, search_policy_clauses

POSITIVE = {"dense_similarity": 0.9, "text_match": 0.9, "graph_proximity": 0.5}
NEGATIVE = {"dense_similarity": 0.1, "text_match": 0.1, "graph_proximity": 0.0}


@pytest.fixture(autouse=True)
def isolated_state():
    runtime_flags.reset()
    ltr.invalidate_cache()
    yield
    runtime_flags.reset()
    ltr.invalidate_cache()


@pytest.fixture
def database(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine)
    app_db.Base.metadata.create_all(engine)
    for module in (app_db, app_main):
        monkeypatch.setattr(module, "engine", engine)
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(app_main, "load_seed_templates", lambda db: 0)
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    monkeypatch.setattr(settings, "rerank_url", "")
    monkeypatch.setattr(settings, "rerank_local_model", "")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "ltr_mode", "off")
    monkeypatch.setattr(settings, "ltr_min_samples", 8)
    monkeypatch.setattr(settings, "ltr_min_auc", 0.6)
    with factory() as db:
        yield db
    engine.dispose()


def samples(pairs=20):
    rows = []
    for _ in range(pairs):
        rows.append(TrainingSample(features=dict(POSITIVE), label=1))
        rows.append(TrainingSample(features=dict(NEGATIVE), label=0))
    return rows


def candidate_rows():
    return [
        {"clause": SimpleNamespace(id=1), "rrf_score": 0.9, "bm25_score": 10.0,
         "dense_score": 0.2, "graph_hops": None},
        {"clause": SimpleNamespace(id=2), "rrf_score": 0.5, "bm25_score": 5.0,
         "dense_score": 0.3, "graph_hops": 2},
        {"clause": SimpleNamespace(id=3), "rrf_score": 0.1, "bm25_score": 1.0,
         "dense_score": 0.95, "graph_hops": 1},
    ]


def headers(permissions: str) -> dict:
    return {
        "X-Internal-Token": settings.ai_internal_token,
        "X-User-Id": "ops-user", "X-Tenant-Id": "default",
        "X-User-Permissions": permissions,
    }


# ===== 特征口径 =====

def test_graph_proximity_uses_inverse_path_length_and_unknown_is_zero():
    assert ltr.graph_proximity(None) == 0.0
    assert ltr.graph_proximity("") == 0.0
    assert ltr.graph_proximity(0) == 0.0
    assert ltr.graph_proximity("bad") == 0.0
    assert ltr.graph_proximity(1) == 0.5
    assert round(ltr.graph_proximity(2), 6) == round(1 / 3, 6)
    # 路径越长信号越弱：单调递减
    assert ltr.graph_proximity(1) > ltr.graph_proximity(3) > 0


def test_batch_features_normalize_text_match_and_clamp_dense():
    rows = candidate_rows()
    features = ltr.candidate_features(rows)
    assert features[0]["text_match"] == 1.0
    assert features[1]["text_match"] == 0.5
    assert features[2]["text_match"] == 0.1
    assert features[0]["dense_similarity"] == 0.2
    assert features[2]["graph_proximity"] == 0.5
    assert features[0]["graph_proximity"] == 0.0
    negative = ltr.candidate_features([{"dense_score": -0.8, "bm25_score": 0.0, "graph_hops": None}])
    assert negative[0]["dense_similarity"] == 0.0


# ===== 训练与门禁 =====

def test_training_rejects_single_class_or_insufficient_samples():
    with pytest.raises(ValueError):
        ltr.train_model([TrainingSample(features=dict(POSITIVE), label=1) for _ in range(20)])
    with pytest.raises(ValueError):
        ltr.train_model(samples(pairs=2))  # 4 < LTR_MIN_SAMPLES=8
    with pytest.raises(ValueError):
        ltr.train_model([TrainingSample(features=dict(POSITIVE), label=2) for _ in range(20)])


def test_training_learns_explainable_weights_and_passes_gate(monkeypatch):
    monkeypatch.setattr(settings, "ltr_min_samples", 8)
    model = ltr.train_model(samples(pairs=20), dataset_digest="unit-test")
    assert model.samples == 40 and model.positives == 20
    for name in ("dense_similarity", "text_match", "graph_proximity"):
        assert model.weights[name] > 0, f"{name} 在可分样本上应为正权重"
    assert model.metrics["auc"] > 0.9 and model.metrics["cv_auc"] > 0.9
    decision = ltr.should_promote(model)
    assert decision["promoted"] is True and decision["reason"] == "ok"
    # 模型分：命中特征的正例必须高于负例
    assert model.score(POSITIVE) > model.score(NEGATIVE)


def test_gate_rejects_unpredictive_model_and_missing_model():
    random.seed(20261026)
    noisy = [
        TrainingSample(features={
            "dense_similarity": random.random(), "text_match": random.random(),
            "graph_proximity": 0.0,
        }, label=random.randint(0, 1))
        for _ in range(80)
    ]
    model = ltr.train_model(noisy, dataset_digest="noise")
    decision = ltr.should_promote(model)
    assert decision["promoted"] is False
    assert "AUC" in decision["reason"]
    assert ltr.should_promote(None)["promoted"] is False
    # 样本数不足的模型也过不了门禁（即使指标好看）
    small = RankingModel(version="small", weights={"text_match": 1.0}, bias=0.0,
                         metrics={"cv_auc": 0.99}, samples=4)
    assert ltr.should_promote(small, min_samples=8)["promoted"] is False


# ===== 三档模式与 RRF 保底 =====

def test_rank_off_shadow_blend_and_fallbacks(monkeypatch):
    monkeypatch.setattr(settings, "ltr_min_samples", 8)
    model = ltr.train_model(samples(pairs=20))

    off_rows, off_info = ltr.rank(candidate_rows(), mode="off", model=model)
    assert [row["clause"].id for row in off_rows] == [1, 2, 3]
    assert off_info["mode"] == "off" and off_info["degraded"] is False

    shadow_rows, shadow_info = ltr.rank(candidate_rows(), mode="shadow", model=model)
    assert [row["clause"].id for row in shadow_rows] == [1, 2, 3], "影子模式不得改线上顺序"
    assert shadow_info["mode"] == "shadow" and shadow_info["modelVersion"] == model.version
    assert all("ltr_score" in row and "blend_score" in row for row in shadow_rows)

    blend_rows, blend_info = ltr.rank(candidate_rows(), mode="blend", model=model, alpha=0.6)
    assert blend_info["mode"] == "blend"
    scores = [row["blend_score"] for row in blend_rows]
    assert scores == sorted(scores, reverse=True), "blend 必须按混合分排序"
    assert all("rrf_score" in row for row in blend_rows), "RRF 分必须保留（保底口径）"
    assert [row["clause"].id for row in blend_rows] != [1, 2, 3], "dense 高的候选应被提到前面"

    missing_rows, missing_info = ltr.rank(candidate_rows(), mode="blend", model=None)
    assert [row["clause"].id for row in missing_rows] == [1, 2, 3]
    assert missing_info["degraded"] is True and missing_info["reason"] == "no-active-model"
    assert missing_info["mode"] == "off"

    class Exploding:
        version = "exploding"

        def score(self, features):
            raise RuntimeError("model boom")

    broken_rows, broken_info = ltr.rank(candidate_rows(), mode="blend", model=Exploding())
    assert [row["clause"].id for row in broken_rows] == [1, 2, 3]
    assert broken_info["degraded"] is True and broken_info["reason"] == "RuntimeError"


# ===== 模型持久化 / 激活门禁 / 审计 =====

def test_model_lifecycle_gate_rollback_and_audit(database):
    model = ltr.train_model(samples(pairs=20), dataset_digest="lifecycle")
    assert ltr.load_active(database) is None
    ltr.save_model(database, model, status="shadow")
    database.commit()
    assert ltr.load_active(database) is None, "shadow 模型不得被检索链路取用"

    weak = RankingModel(version="weak-v0", weights={"text_match": 0.1}, bias=0.0,
                        metrics={"cv_auc": 0.51, "foldUnit": "group"}, samples=40)
    ltr.save_model(database, weak)
    database.commit()
    with pytest.raises(HTTPException) as error:
        ltr.activate_model(database, "weak-v0")
    assert error.value.status_code == 409
    assert "门禁" in error.value.detail["message"]
    # force 不是后门：从未激活过的弱模型即使 force 也不允许上线
    with pytest.raises(HTTPException) as error:
        ltr.activate_model(database, "weak-v0", force=True)
    assert error.value.status_code == 409
    assert "回滚" in error.value.detail["message"]

    activated = ltr.activate_model(database, model.version, operator="ops")
    database.commit()
    assert activated["status"] == "active" and activated["gate"]["promoted"] is True
    assert ltr.load_active(database).version == model.version

    # 同版本必须同内容：否则一次"重复落库"就能静默改掉线上权重
    tampered = RankingModel(version=model.version, weights={"text_match": -9.0}, bias=0.0,
                            metrics={"cv_auc": 0.99}, samples=40)
    with pytest.raises(HTTPException) as error:
        ltr.save_model(database, tampered)
    assert error.value.status_code == 409
    assert ltr.load_active(database).version == model.version, "被篡改的同版本不得影响线上模型"

    second = ltr.train_model(samples(pairs=20), dataset_digest="lifecycle-2")
    ltr.save_model(database, second)
    database.commit()
    ltr.activate_model(database, second.version, operator="ops")
    database.commit()
    assert ltr.load_active(database).version == second.version
    rows = {row["version"]: row for row in ltr.model_rows(database)}
    assert rows[model.version]["status"] == "retired", "激活新模型必须退役旧模型"

    # 回滚到曾激活过的版本：force 的唯一合法用途
    rollback = ltr.activate_model(database, model.version, force=True, operator="ops")
    database.commit()
    assert rollback["status"] == "active" and rollback["gate"]["promoted"] is True
    assert ltr.load_active(database).version == model.version

    actions = {row.action for row in database.query(GovernanceAudit).all()}
    assert "ltr.activate" in actions

    ltr.retire_model(database, model.version, operator="ops")
    database.commit()
    assert ltr.load_active(database) is None

# ===== 运维端点 =====

def test_ltr_endpoints_train_gate_and_permissions(database):
    """训练与指标必须由服务端产生：客户端自报 weights / cv_auc 的入口已不存在。"""
    body = {
        "samples": [{"features": dict(POSITIVE), "label": 1},
                    {"features": dict(NEGATIVE), "label": 0}] * 10,
        "groups": [f"case-{index}" for index in range(10) for _ in range(2)],
        "datasetDigest": "endpoint",
    }
    with TestClient(app_main.app) as client:
        assert client.get("/api/agent/ltr", headers=headers("policy:read")).status_code == 403
        status = client.get("/api/agent/ltr", headers=headers("agent:audit"))
        assert status.status_code == 200
        assert status.json()["mode"] == "off" and status.json()["activeModel"] is None
        assert client.post(
            "/api/agent/ltr/train", json=body, headers=headers("agent:audit"),
        ).status_code == 403
        # 样本不足：服务端拒绝训练，不落库、不返回"凑合能用"的模型
        too_few = {"samples": body["samples"][:2], "groups": [], "datasetDigest": "tiny"}
        assert client.post(
            "/api/agent/ltr/train", json=too_few, headers=headers("agent:admin"),
        ).status_code == 422
        trained = client.post(
            "/api/agent/ltr/train", json={**body, "activate": True}, headers=headers("agent:admin"),
        )
        assert trained.status_code == 201, trained.text
        payload = trained.json()
        assert payload["status"] == "active" and payload["gate"]["promoted"] is True
        assert payload["gate"]["foldUnit"] == "group", "门禁口径必须按 case 分组折"
        version = payload["version"]
        listed = client.get("/api/agent/ltr", headers=headers("agent:audit")).json()
        assert listed["activeModel"]["version"] == version
        # 自报指标注册入口已移除：塞不进一个假的 cv_auc
        assert client.post(
            "/api/agent/ltr/models", json={"version": "fake"}, headers=headers("agent:admin"),
        ).status_code == 404
        assert client.post(
            f"/api/agent/ltr/models/{version}/retire", json={}, headers=headers("agent:audit"),
        ).status_code == 403
        assert client.post(
            f"/api/agent/ltr/models/{version}/retire", json={}, headers=headers("agent:admin"),
        ).status_code == 200
    assert database.query(GovernanceAudit).filter(GovernanceAudit.action == "ltr.train").count() == 1

# ===== 检索链路集成 =====

def test_policy_retrieval_ltr_modes_and_runtime_flag(database, monkeypatch):
    create_policy_document(
        database, title="研发补助办法",
        content="第一条 企业申请研发补助应当提交研发费用归集表与营业执照复印件。",
    )
    database.commit()
    baseline = search_policy_clauses(database, "研发补助申请材料")
    base_ids = [row["clause"].id for row in baseline]
    assert baseline[0]["retrieval"]["ltr"]["mode"] == "off"

    # 开了 shadow 但没有激活模型：退回 RRF 并明确标记 degraded（不允许静默）
    monkeypatch.setattr(settings, "ltr_mode", "shadow")
    no_model = search_policy_clauses(database, "研发补助申请材料")
    assert no_model[0]["retrieval"]["ltr"]["degraded"] is True
    assert no_model[0]["retrieval"]["ltr"]["reason"] == "no-active-model"
    assert [row["clause"].id for row in no_model] == base_ids
    response = answer_policy(database, PolicyQuery(question="研发补助申请材料？"))
    assert "LTR 排序已启用但没有激活模型" in " ".join(response["degradationReasons"])

    model = ltr.train_model(samples(pairs=20), dataset_digest="integration")
    ltr.save_model(database, model)
    ltr.activate_model(database, model.version)
    database.commit()

    shadow = search_policy_clauses(database, "研发补助申请材料")
    info = shadow[0]["retrieval"]["ltr"]
    assert info["mode"] == "shadow" and info["modelVersion"] == model.version
    assert [row["clause"].id for row in shadow] == base_ids, "影子模式不得改变线上顺序"
    assert shadow[0]["retrieval"]["ltrScore"] is not None
    assert shadow[0]["retrieval"]["blendScore"] is not None

    monkeypatch.setattr(settings, "ltr_mode", "blend")
    monkeypatch.setattr(settings, "ltr_blend_alpha", 0.8)
    blended = search_policy_clauses(database, "研发补助申请材料")
    assert blended[0]["retrieval"]["ltr"]["mode"] == "blend"
    scores = [row["retrieval"]["blendScore"] for row in blended]
    assert scores == sorted(scores, reverse=True)

    # G5 运行时开关：显式关闭后必须回到 RRF 口径，并出现在降级说明里
    runtime_flags.set_flag("ltr", False, operator="ops", reason="模拟模型侧故障")
    stopped = search_policy_clauses(database, "研发补助申请材料")
    assert stopped[0]["retrieval"]["ltr"]["mode"] == "off"
    assert stopped[0]["retrieval"]["ltr"]["reason"] == "runtime-flag-ltr-off"
    assert "ltr" in stopped[0]["retrieval"]["runtimeFlags"]
    assert [row["clause"].id for row in stopped] == base_ids
    assert ltr.active_mode() == ("off", "runtime-flag-ltr-off")
# ===== 审查发现的加固点（NaN / 同版本篡改 / blend 必须进入精排基准）=====

def test_non_finite_scores_fall_back_to_rrf(monkeypatch):
    monkeypatch.setattr(settings, "ltr_min_samples", 8)

    class NanModel:
        version = "nan-model"

        def score(self, features):
            return float("nan")

    rows, info = ltr.rank(candidate_rows(), mode="blend", model=NanModel())
    assert [row["clause"].id for row in rows] == [1, 2, 3]
    assert info["degraded"] is True and info["reason"] == "ValueError"
    assert info["mode"] == "off"


def test_training_rejects_non_finite_features(monkeypatch):
    monkeypatch.setattr(settings, "ltr_min_samples", 4)
    bad = [
        TrainingSample(features={**POSITIVE, "text_match": float("nan")}, label=1),
        TrainingSample(features=dict(NEGATIVE), label=0),
    ]
    with pytest.raises(ValueError):
        ltr.train_model(bad)


def test_save_model_refuses_active_status_and_unknown_features(database):
    model = ltr.train_model(samples(pairs=20), dataset_digest="guard")
    with pytest.raises(HTTPException) as error:
        ltr.save_model(database, model, status="active")
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        ltr.save_model(database, RankingModel(version="weird", weights={"unknown_feature": 1.0}, bias=0.0))
    assert error.value.status_code == 422
    with pytest.raises(HTTPException):
        ltr.save_model(
            database,
            RankingModel(version="nan-bias", weights={"text_match": 1.0}, bias=float("nan")),
        )


def test_rerank_uses_ltr_blend_as_ranking_basis():
    """blend 必须进入精排的排序基准，否则"渐进替换 RRF"在精排降级路径上会被整段抹掉。"""
    from types import SimpleNamespace as NS

    from app.agent.retrieval import rerank

    def candidate(clause_id, rrf, blend=None):
        row = {
            "clause": NS(id=clause_id, content="研发补助材料"), "document": NS(title="研发补助材料"),
            "rrf_score": rrf,
        }
        if blend is not None:
            row["blend_score"] = blend
        return row

    ranked, _info = rerank("研发补助材料", [candidate(1, 0.9, 0.1), candidate(2, 0.1, 0.9)])
    assert [item["clause"].id for item in ranked][0] == 2, "词法重叠相同时应由 blend 分决定顺序"
    fallback, _info = rerank("研发补助材料", [candidate(1, 0.9), candidate(2, 0.1)])
    assert [item["clause"].id for item in fallback][0] == 1, "没有 blend 时必须回到 RRF 口径"