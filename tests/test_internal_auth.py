from datetime import datetime
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings, settings
from app.db import get_db
from app.main import app as main_app
from app.meeting import routers as meeting_routers
from app.opinion import routers as opinion_routers
from app.routers import intelligence, qualification

INTERNAL_INTELLIGENCE_ENDPOINTS = (
    ("/internal/intelligence/tasks/1/dispatch", 202),
    ("/internal/intelligence/reports/generate", 200),
)
VALID_PRODUCTION_TOKENS = {
    "ai_internal_token": "ai-internal-token-0123456789abcdef",
    "opinion_java_token": "opinion-java-token-0123456789abcdef",
    "opinion_internal_token": "opinion-internal-token-0123456789abcdef",
    "meeting_java_token": "meeting-java-token-0123456789abcdef",
    "meeting_internal_token": "meeting-internal-token-0123456789abcdef",
}


@pytest.fixture
def intelligence_client(monkeypatch):
    app = FastAPI()
    app.include_router(intelligence.internal_router)
    app.dependency_overrides[get_db] = lambda: object()

    import app.services.intelligence as intel_svc

    monkeypatch.setattr(intel_svc, "run_collection_task", lambda task_id: {"id": task_id, "status": "running"})
    monkeypatch.setattr(intel_svc, "rebuild_clusters", lambda since_days=30: [])
    monkeypatch.setattr(intel_svc, "generate_report", lambda period="daily": {"id": 1, "period": period})
    return TestClient(app)


@pytest.mark.parametrize("path,expected_status", INTERNAL_INTELLIGENCE_ENDPOINTS)
def test_internal_intelligence_rejects_missing_or_invalid_token(intelligence_client, path, expected_status):
    assert intelligence_client.post(path).status_code == 403
    assert intelligence_client.post(path, headers={"X-Internal-Token": "wrong-token"}).status_code == 403


@pytest.mark.parametrize("path,expected_status", INTERNAL_INTELLIGENCE_ENDPOINTS)
def test_internal_intelligence_accepts_valid_token(intelligence_client, path, expected_status):
    response = intelligence_client.post(path, headers={"X-Internal-Token": settings.ai_internal_token})

    assert response.status_code == expected_status


def test_internal_health_requires_valid_token():
    client = TestClient(main_app)

    assert client.get("/internal/health").status_code == 403
    assert client.get("/internal/health", headers={"X-Internal-Token": "wrong-token"}).status_code == 403

    response = client.get("/internal/health", headers={"X-Internal-Token": settings.ai_internal_token})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize(
    ("router", "path", "token"),
    (
        (opinion_routers.internal_router, "/internal/opinion/ping", settings.opinion_internal_token),
        (meeting_routers.internal_router, "/internal/meeting/ping", settings.meeting_internal_token),
    ),
)
def test_domain_internal_health_requires_its_own_token(router, path, token):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    assert client.get(path).status_code == 403
    assert client.get(path, headers={"X-Internal-Token": "wrong-token"}).status_code == 403

    response = client.get(path, headers={"X-Internal-Token": token})

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_qualification_internal_endpoint_requires_valid_token():
    app = FastAPI()
    app.include_router(qualification.router)
    client = TestClient(app)
    files = {"file": ("guide.txt", b"\xe7\x94\xb3\xe6\x8a\xa5\xe8\xa6\x81\xe6\xb1\x82", "text/plain")}

    assert client.post("/internal/qual/parse-guide", files=files).status_code == 403
    assert (
        client.post(
            "/internal/qual/parse-guide",
            files=files,
            headers={"X-Internal-Token": "wrong-token"},
        ).status_code
        == 403
    )

    response = client.post(
        "/internal/qual/parse-guide",
        files=files,
        headers={"X-Internal-Token": settings.ai_internal_token},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "申报要求"


@pytest.mark.parametrize(
    ("field", "invalid_token"),
    (
        ("ai_internal_token", "eaos-internal-token-change-me"),
        ("opinion_java_token", "eaos-opinion-internal-dev-token"),
        ("opinion_internal_token", ""),
        ("meeting_java_token", "short-token"),
        ("meeting_internal_token", "eaos-meeting-internal-dev-token"),
    ),
)
def test_production_rejects_default_or_weak_internal_tokens(field, invalid_token):
    values = {**VALID_PRODUCTION_TOKENS, field: invalid_token}

    with pytest.raises(ValidationError):
        Settings(app_env="production", **values)


def test_production_accepts_non_default_internal_tokens():
    configured = Settings(app_env="production", **VALID_PRODUCTION_TOKENS)

    assert configured.ai_internal_token == VALID_PRODUCTION_TOKENS["ai_internal_token"]


def test_production_default_internal_token_prevents_application_import():
    environment = {
        **os.environ,
        "APP_ENV": "production",
        **{
            field.upper(): value
            for field, value in VALID_PRODUCTION_TOKENS.items()
            if field != "ai_internal_token"
        },
    }
    environment["AI_INTERNAL_TOKEN"] = "eaos-internal-token-change-me"

    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode != 0
    assert "生产环境必须为服务间令牌配置至少 16 个字符的非默认随机值" in result.stderr
