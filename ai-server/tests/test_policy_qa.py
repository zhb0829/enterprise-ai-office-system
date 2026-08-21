from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import main as app_main
from app.models import PolicyDocument


def test_policy_chat_refuses_without_evidence(monkeypatch):
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

    with TestClient(app_main.app) as client:
        response = client.post("/api/policy/chat", json={"question": "不存在的法规条款是什么？"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["confidence"] == "none"
    assert payload["clauses"] == []
    assert "未检索到" in payload["answer"]
    assert payload["riskFlags"]


def test_policy_chat_returns_citations_and_compliance_disclaimer(monkeypatch):
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

    with session_factory() as db:
        app_db.Base.metadata.create_all(bind=engine)
        document = PolicyDocument(
            title="高新技术企业认定管理办法",
            doc_number="国科发火〔2016〕32号",
            issuing_authority="科技部",
            level="部门规章",
            status="现行有效",
            industry_tags=["科技"],
            source_url="https://example.com/policy",
            text_content="第一条 本办法适用于高新技术企业认定。\n第十一条 企业研发费用占销售收入比例应符合相关要求。",
            parse_status="已完成",
        )
        db.add(document)
        db.commit()

    from app.services.policy import create_policy_document

    with session_factory() as db:
        db.query(PolicyDocument).delete()
        db.commit()
        create_policy_document(
            db,
            title="高新技术企业认定管理办法",
            content="第一条 本办法适用于高新技术企业认定。\n第十一条 企业研发费用占销售收入比例应符合相关要求。",
            issuing_authority="科技部",
            level="部门规章",
            industry_tags=["科技"],
            source_url="https://example.com/policy",
        )

    with TestClient(app_main.app) as client:
        response = client.post(
            "/api/policy/chat",
            json={"question": "高新技术企业研发费用比例要求？", "industry": "科技"},
        )
        compliance = client.post(
            "/api/policy/compliance/check",
            json={"businessDesc": "公司从事高新技术产品研发、销售及相关技术服务。", "industry": "科技"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["clauses"]
    assert payload["clauses"][0]["sourceUrl"] == "https://example.com/policy"
    assert "[引用1]" in payload["answer"]
    assert compliance.status_code == 200
    assert "不构成法律意见" in compliance.json()["disclaimer"]
