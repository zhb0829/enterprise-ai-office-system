"""Agent roles, isolated memories, immutable knowledge and governance."""
from alembic import op
import sqlalchemy as sa

revision = "9a2_agent_p1"
down_revision = "8f1_agent_p0"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("draft", "reference_material"):
        op.add_column(table, sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"))
        op.add_column(table, sa.Column("department_id", sa.String(64), nullable=False, server_default=""))
        op.add_column(table, sa.Column("classification", sa.String(16), nullable=False, server_default="internal"))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.add_column("reference_material", sa.Column("owner_id", sa.String(64), nullable=False, server_default=""))
    op.add_column("agent_run", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"))
    op.add_column("agent_run", sa.Column("department_id", sa.String(64), nullable=False, server_default=""))
    op.create_index("ix_agent_run_tenant_id", "agent_run", ["tenant_id"])
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("department_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "department_id", "user_id", "scope", "session_id", "kind", "key", name="uq_agent_memory_scope_key"),
    )
    for field in ("tenant_id", "user_id", "session_id", "expires_at"):
        op.create_index(f"ix_agent_memory_{field}", "agent_memory", [field])
    op.create_table(
        "governance_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("department_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource", sa.String(256), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    for field in ("tenant_id", "user_id", "trace_id", "expires_at"):
        op.create_index(f"ix_governance_audit_{field}", "governance_audit", [field])
    op.create_table(
        "knowledge_head",
        sa.Column("namespace", sa.String(128), primary_key=True),
        sa.Column("release_id", sa.String(64), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("next_version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "knowledge_release",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("namespace", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("namespace", "version", name="uq_knowledge_namespace_version"),
    )
    for field in ("namespace", "effective_at"):
        op.create_index(f"ix_knowledge_release_{field}", "knowledge_release", [field])
    op.create_table(
        "knowledge_entry",
        sa.Column("release_id", sa.String(64), sa.ForeignKey("knowledge_release.id"), primary_key=True),
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("chunks", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("department_id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    for table in ("knowledge_entry", "knowledge_release", "knowledge_head", "governance_audit", "agent_memory"):
        op.drop_table(table)
    op.drop_index("ix_agent_run_tenant_id", table_name="agent_run")
    op.drop_column("agent_run", "department_id")
    op.drop_column("agent_run", "tenant_id")
    op.drop_column("reference_material", "owner_id")
    for table in ("reference_material", "draft"):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        for column in ("classification", "department_id", "tenant_id"):
            op.drop_column(table, column)
