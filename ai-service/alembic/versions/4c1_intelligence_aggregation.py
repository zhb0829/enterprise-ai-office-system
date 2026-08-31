"""industry and competitor intelligence aggregation

Revision ID: 4c1_intelligence_aggregation
Revises: 2a4f_policy_qa
"""
from alembic import op
import sqlalchemy as sa


revision = "4c1_intelligence_aggregation"
down_revision = "2a4f_policy_qa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("competitors", sa.JSON(), nullable=False),
        sa.Column("frequency", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("health_status", sa.String(32), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("url"),
    )
    op.create_index("ix_source_config_name", "source_config", ["name"])
    op.create_index("ix_source_config_type", "source_config", ["type"])
    op.create_index("ix_source_config_status", "source_config", ["status"])

    op.create_table(
        "collected_article",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("author", sa.String(256), nullable=False),
        sa.Column("publish_time", sa.DateTime(), nullable=True),
        sa.Column("collected_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("title_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source_config.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("content_hash"),
    )
    op.create_index("ix_collected_article_source_id", "collected_article", ["source_id"])
    op.create_index("ix_collected_article_collected_at", "collected_article", ["collected_at"])
    op.create_index("ix_collected_article_content_hash", "collected_article", ["content_hash"])
    op.create_index("ix_collected_article_title_hash", "collected_article", ["title_hash"])
    op.create_index("ix_collected_article_status", "collected_article", ["status"])

    op.create_table(
        "article_cluster",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("topic", sa.String(256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("article_ids", sa.JSON(), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("time_start", sa.DateTime(), nullable=True),
        sa.Column("time_end", sa.DateTime(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_article_cluster_topic", "article_cluster", ["topic"])
    op.create_index("ix_article_cluster_created_at", "article_cluster", ["created_at"])

    op.create_table(
        "intelligence_report",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("period", sa.String(64), nullable=False),
        sa.Column("topic_tags", sa.JSON(), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("trend", sa.JSON(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("risk_flags", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_intelligence_report_period", "intelligence_report", ["period"])

    op.create_table(
        "collection_task_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("celery_task_id", sa.String(128), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("items_count", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["source_config.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collection_task_log_source_id", "collection_task_log", ["source_id"])
    op.create_index("ix_collection_task_log_celery_task_id", "collection_task_log", ["celery_task_id"])
    op.create_index("ix_collection_task_log_status", "collection_task_log", ["status"])
    op.create_index("ix_collection_task_log_created_at", "collection_task_log", ["created_at"])


def downgrade() -> None:
    for name in ("ix_collection_task_log_created_at", "ix_collection_task_log_status", "ix_collection_task_log_celery_task_id", "ix_collection_task_log_source_id"):
        op.drop_index(name, table_name="collection_task_log")
    op.drop_table("collection_task_log")
    op.drop_index("ix_intelligence_report_period", table_name="intelligence_report")
    op.drop_table("intelligence_report")
    op.drop_index("ix_article_cluster_created_at", table_name="article_cluster")
    op.drop_index("ix_article_cluster_topic", table_name="article_cluster")
    op.drop_table("article_cluster")
    for name in ("ix_collected_article_status", "ix_collected_article_title_hash", "ix_collected_article_content_hash", "ix_collected_article_collected_at", "ix_collected_article_source_id"):
        op.drop_index(name, table_name="collected_article")
    op.drop_table("collected_article")
    for name in ("ix_source_config_status", "ix_source_config_type", "ix_source_config_name"):
        op.drop_index(name, table_name="source_config")
    op.drop_table("source_config")
