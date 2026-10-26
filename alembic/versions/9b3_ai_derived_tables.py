"""Migrate Python-owned derived AI tables previously created only on startup."""
from alembic import op
import sqlalchemy as sa

revision = "9b3_ai_derived"
down_revision = "9a2_agent_p1"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    tables = {
        "meeting_knowledge_index": [
            sa.Column("conference_id", sa.Integer(), nullable=False),
            sa.Column("card_type", sa.String(32), nullable=False),
            sa.Column("title", sa.String(256), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding", sa.JSON(), nullable=False),
            sa.Column("source_ref", sa.JSON(), nullable=False),
        ],
        "opinion_ai_run": [
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("article_id", sa.Integer(), nullable=False),
            sa.Column("monitor_id", sa.Integer(), nullable=False),
            sa.Column("stage", sa.String(32), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("source_type", sa.String(16), nullable=False),
            sa.Column("model", sa.String(128), nullable=False),
            sa.Column("error", sa.Text(), nullable=False),
            sa.Column("meta", sa.JSON(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        ],
        "opinion_ai_model_call": [
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("stage", sa.String(32), nullable=False),
            sa.Column("model", sa.String(128), nullable=False),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("prompt_version", sa.String(64), nullable=False),
            sa.Column("input_chars", sa.Integer(), nullable=False),
            sa.Column("output_chars", sa.Integer(), nullable=False),
            sa.Column("latency_ms", sa.Integer(), nullable=False),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("sent_hash", sa.String(64), nullable=False),
        ],
        "opinion_case_chunk": [
            sa.Column("case_id", sa.Integer(), nullable=False),
            sa.Column("case_title", sa.String(256), nullable=False),
            sa.Column("event_type", sa.String(128), nullable=False),
            sa.Column("risk_level", sa.String(16), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("embedding", sa.JSON(), nullable=False),
            sa.Column("meta", sa.JSON(), nullable=False),
        ],
    }
    indexes = {
        "meeting_knowledge_index": ("conference_id", "card_type"),
        "opinion_ai_run": ("run_id", "task_id", "article_id", "monitor_id"),
        "opinion_ai_model_call": ("run_id",),
        "opinion_case_chunk": ("case_id", "event_type"),
    }
    for name, columns in tables.items():
        if name in existing:
            continue
        op.create_table(name, sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
                        *columns, sa.Column("created_at", sa.DateTime(), nullable=False,
                                           server_default=sa.func.now()))
        for column in indexes[name]:
            op.create_index(f"ix_{name}_{column}", name, [column])


def downgrade():
    for name in ("opinion_case_chunk", "opinion_ai_model_call", "opinion_ai_run", "meeting_knowledge_index"):
        op.drop_table(name)
