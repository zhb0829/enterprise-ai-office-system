"""Unified agent audit, policy validity and human review."""
from alembic import op
import sqlalchemy as sa

revision = "8f1_agent_p0"
down_revision = "7e4_remove_opinion_feature"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("policy_document", sa.Column("expiry_date", sa.DateTime(), nullable=True))
    op.add_column("policy_document", sa.Column("region", sa.String(128), nullable=False, server_default=""))
    op.add_column("policy_document", sa.Column("policy_version", sa.String(64), nullable=False, server_default=""))
    op.create_index("ix_policy_document_region", "policy_document", ["region"])
    op.create_table(
        "agent_run",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("intent", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("verification_result", sa.JSON(), nullable=False),
        sa.Column("final_answer", sa.JSON(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    for field in ("trace_id", "user_id", "session_id", "intent", "status"):
        op.create_index(f"ix_agent_run_{field}", "agent_run", [field])
    op.create_table(
        "draft_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("draft_id", sa.String(64), sa.ForeignKey("draft.id"), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_draft_evidence_draft_id", "draft_evidence", ["draft_id"])
    op.create_table(
        "draft_review",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("draft_id", sa.String(64), sa.ForeignKey("draft.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_draft_review_draft_id", "draft_review", ["draft_id"])
    op.create_index("ix_draft_review_reviewer_id", "draft_review", ["reviewer_id"])


def downgrade():
    op.drop_table("draft_review")
    op.drop_table("draft_evidence")
    op.drop_table("agent_run")
    op.drop_index("ix_policy_document_region", table_name="policy_document")
    op.drop_column("policy_document", "policy_version")
    op.drop_column("policy_document", "region")
    op.drop_column("policy_document", "expiry_date")
