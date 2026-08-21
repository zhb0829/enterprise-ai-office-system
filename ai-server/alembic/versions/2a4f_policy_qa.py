"""行业政策法规问答表

Revision ID: 2a4f_policy_qa
Revises: 9b7a0d3f4c21
"""
from alembic import op
import sqlalchemy as sa


revision = "2a4f_policy_qa"
down_revision = "9b7a0d3f4c21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_document",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("doc_number", sa.String(length=128), nullable=False),
        sa.Column("issuing_authority", sa.String(length=256), nullable=False),
        sa.Column("level", sa.String(length=64), nullable=False),
        sa.Column("publish_date", sa.DateTime(), nullable=True),
        sa.Column("effective_date", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("industry_tags", sa.JSON(), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=False),
        sa.Column("file_path", sa.String(length=512), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("parse_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("title", "doc_number", "level", "status", "parse_status"):
        op.create_index(f"ix_policy_document_{column}", "policy_document", [column], unique=False)

    op.create_table(
        "policy_clause",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("doc_id", sa.Integer(), nullable=False),
        sa.Column("chapter_path", sa.String(length=256), nullable=False),
        sa.Column("article_no", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["doc_id"], ["policy_document.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_policy_clause_doc_id", "policy_clause", ["doc_id"], unique=False)
    op.create_index("ix_policy_clause_article_no", "policy_clause", ["article_no"], unique=False)

    op.create_table(
        "qa_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("feedback", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qa_log_session_id", "qa_log", ["session_id"], unique=False)

    op.create_table(
        "compliance_report",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("business_desc", sa.Text(), nullable=False),
        sa.Column("industry", sa.String(length=128), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_compliance_report_industry", "compliance_report", ["industry"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_compliance_report_industry", table_name="compliance_report")
    op.drop_table("compliance_report")
    op.drop_index("ix_qa_log_session_id", table_name="qa_log")
    op.drop_table("qa_log")
    op.drop_index("ix_policy_clause_article_no", table_name="policy_clause")
    op.drop_index("ix_policy_clause_doc_id", table_name="policy_clause")
    op.drop_table("policy_clause")
    for column in ("parse_status", "status", "level", "doc_number", "title"):
        op.drop_index(f"ix_policy_document_{column}", table_name="policy_document")
    op.drop_table("policy_document")
