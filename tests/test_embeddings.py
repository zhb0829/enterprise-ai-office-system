from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import main as app_main
from app.services import materials


def test_embed_texts_uses_configured_client_in_batches(monkeypatch):
    calls: list[list[str]] = []

    class FakeEmbeddingClient:
        is_configured = True

        def embed(self, texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[float(index), 1.0] for index, _ in enumerate(texts)]

    monkeypatch.setattr(materials.settings, "embedding_batch_size", 2)

    vectors = materials.embed_texts(["第一条", "第二条", "第三条"], client=FakeEmbeddingClient())

    assert calls == [["第一条", "第二条"], ["第三条"]]
    assert vectors == [[0.0, 1.0], [1.0, 1.0], [0.0, 1.0]]


def test_embed_texts_falls_back_only_when_embedding_is_not_configured():
    class OfflineEmbeddingClient:
        is_configured = False

    vectors = materials.embed_texts(["高新技术企业研发费用"], client=OfflineEmbeddingClient())

    assert len(vectors) == 1
    assert len(vectors[0]) == materials.EMBEDDING_DIMS


def test_remote_embedding_does_not_compare_legacy_hash_vectors(monkeypatch):
    monkeypatch.setattr(materials.settings, "embedding_api_key", "configured")
    monkeypatch.setattr(materials.settings, "embedding_model", "text-embedding-3-small")

    assert not materials.embedding_is_compatible(
        {"embedding_backend": "hash-fallback", "embedding_dimensions": 64},
        [0.1, 0.2],
    )
    assert materials.embedding_is_compatible(
        {
            "embedding_backend": "remote",
            "embedding_model": "text-embedding-3-small",
            "embedding_dimensions": 2,
        },
        [0.1, 0.2],
    )


def test_policy_search_returns_503_when_remote_embedding_fails(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(app_db, "engine", engine)
    monkeypatch.setattr(app_db, "SessionLocal", session_factory)
    monkeypatch.setattr(app_main, "engine", engine)
    monkeypatch.setattr(app_main, "SessionLocal", session_factory)
    monkeypatch.setattr(app_main, "load_seed_templates", lambda db: 0)
    monkeypatch.setattr(
        "app.routers.policy.search_policy_clauses",
        lambda *args, **kwargs: (_ for _ in ()).throw(materials.EmbeddingError("Embedding 服务不可用")),
    )

    with TestClient(app_main.app) as client:
        response = client.get("/api/policy/search", params={"q": "研发费用"})

    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "Embedding 服务不可用"
