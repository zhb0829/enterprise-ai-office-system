from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as app_db
from app import main as app_main
from app.models import PolicyDocument
from app.routers.policy import parse_policy_upload
from app.services.llm import LLMClient
from app.services import materials
from app.services.policy import PublicSourceFetchError


@pytest.fixture(autouse=True)
def use_offline_embeddings(monkeypatch):
    """政策测试不依赖本机 .env 中配置的远端 Embedding 服务。"""
    monkeypatch.setattr(materials.settings, "embedding_api_key", "")


@pytest.fixture()
def sqlite_app(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    app_db.Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(app_db, "engine", engine)
    monkeypatch.setattr(app_db, "SessionLocal", session_factory)
    monkeypatch.setattr(app_main, "engine", engine)
    monkeypatch.setattr(app_main, "SessionLocal", session_factory)
    monkeypatch.setattr(app_main, "load_seed_templates", lambda db: 0)


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


def test_policy_interpret_normalizes_string_fields_from_llm(monkeypatch):
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

    from app.services.policy import create_policy_document

    with session_factory() as db:
        app_db.Base.metadata.create_all(bind=engine)
        document = create_policy_document(
            db,
            title="测试政策",
            content="第一条 企业应当保留研发费用相关资料。",
            industry_tags=["科技"],
        )
        clause_id = document.clauses[0].id

    class StringFieldLLM(LLMClient):
        is_mock = False

        def __init__(self):
            pass

        def chat_json(self, *args, **kwargs):
            return {
                "plainSummary": "应保留研发资料。",
                "applicableObjects": "开展研发活动的企业",
                "obligations": "保留相关资料",
                "prohibitions": "不得伪造资料",
                "consequences": "可能承担相应责任",
            }

    from app.services import policy as policy_service

    with session_factory() as db:
        result = policy_service.interpret_clause(db, type("Request", (), {"clauseId": clause_id, "clauseText": None, "docTitle": "", "articleNo": "", "sourceUrl": ""})(), llm=StringFieldLLM())

    assert result["applicableObjects"] == ["开展研发活动的企业"]
    assert result["obligations"] == ["保留相关资料"]


def test_policy_url_import_returns_clear_message_for_source_403(monkeypatch, sqlite_app):
    monkeypatch.setattr(
        "app.routers.policy.fetch_public_source",
        lambda url: (_ for _ in ()).throw(
            PublicSourceFetchError(403, "目标网站禁止程序化采集，请下载政策文件后通过“上传政策文件”入库。")
        ),
    )

    with TestClient(app_main.app) as client:
        response = client.post(
            "/api/policy/documents/from-url",
            json={"url": "https://www.gov.cn/example", "industryTags": []},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["message"] == "目标网站禁止程序化采集，请下载政策文件后通过“上传政策文件”入库。"


def test_parse_policy_upload_reuses_material_parser():
    assert parse_policy_upload("policy.txt", "政策文本".encode("utf-8")) == "政策文本"
