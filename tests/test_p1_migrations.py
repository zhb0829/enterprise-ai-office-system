"""Opt-in migration verification against an empty disposable PostgreSQL database."""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings

URL = os.environ.get("P1_TEST_DATABASE_URL", "")


@pytest.mark.skipif(not URL, reason="requires P1_TEST_DATABASE_URL for a disposable PostgreSQL database")
def test_p1_postgres_upgrade_downgrade_and_java_ownership(monkeypatch):
    engine = create_engine(URL)
    assert inspect(engine).get_table_names() == [], "migration test requires an empty disposable database"
    monkeypatch.setattr(settings, "database_url", URL)
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE opinion_monitor (id BIGINT PRIMARY KEY, marker TEXT)"))
        connection.execute(text("INSERT INTO opinion_monitor VALUES (1, 'Java-owned sentinel')"))
    command.upgrade(config, "head")
    names = set(inspect(engine).get_table_names())
    assert {
        "agent_run", "agent_memory", "governance_audit", "knowledge_head", "knowledge_release",
        "knowledge_entry", "meeting_knowledge_index", "opinion_ai_run", "opinion_ai_model_call",
        "opinion_case_chunk",
        # G9：LTR 排序模型表
        "ranking_model",
    } <= names
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT marker FROM opinion_monitor WHERE id=1")) == "Java-owned sentinel"
    assert {"tenant_id", "department_id", "classification"} <= {
        c["name"] for c in inspect(engine).get_columns("draft")}
    assert "classification" in {c["name"] for c in inspect(engine).get_columns("agent_run")}
    # G2：qa_log 承载线上反馈与运行关联
    assert {"tenant_id", "user_id", "run_id", "resolved", "feedback_reason", "feedback_at"} <= {
        c["name"] for c in inspect(engine).get_columns("qa_log")}
    command.downgrade(config, "8f1_agent_p0")
    assert "agent_memory" not in inspect(engine).get_table_names()
    # G2 回滚对称性：qa_log 的反馈列必须被 downgrade 移除
    assert "resolved" not in {c["name"] for c in inspect(engine).get_columns("qa_log")}
    assert "run_id" not in {c["name"] for c in inspect(engine).get_columns("qa_log")}
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM opinion_monitor")) == 1
    engine.dispose()
