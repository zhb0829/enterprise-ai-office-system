"""Retire only legacy Python opinion tables.

The Java P1 opinion module owns all ``opinion_*`` business tables. This
revision must never drop those tables, otherwise an Alembic upgrade can
destroy Java-owned data.
"""

Revision ID: 7e4_remove_opinion_feature
Revises: 4c1_intelligence_aggregation
"""
from alembic import op


revision = "7e4_remove_opinion_feature"
down_revision = "4c1_intelligence_aggregation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These tables belonged to an abandoned Python-only prototype. Never
    # include Java-owned opinion_* tables here.
    for table in (
        "opinion_report_export",
        "alert_audit_log",
        "alert_notification",
        "alert_event",
        "alert_rule",
        "monitor_keyword_source",
        "monitor_keyword",
        "notification_channel",
        "retention_run_log",
        "data_retention_policy",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    # Legacy prototype tables are intentionally not recreated.
    pass
