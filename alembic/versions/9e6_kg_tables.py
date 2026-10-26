"""知识图谱三张表（G1）。

与 `app/kg/models.py` 字段保持一致：图数据自带 tenant_id + classification，
检索侧必须再走一次 `Principal.can_read`——`install_data_isolation` 不覆盖图数据。
"""
from alembic import op
import sqlalchemy as sa

revision = "9e6_kg_tables"
down_revision = "9d5_eval_feedback"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "kg_entity" not in existing:
        op.create_table(
            "kg_entity",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
            sa.Column("department_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("classification", sa.String(16), nullable=False, server_default="internal"),
            sa.Column("name", sa.String(256), nullable=False),
            sa.Column("norm_key", sa.String(256), nullable=False),
            sa.Column("entity_type", sa.String(64), nullable=False),
            sa.Column("aliases", sa.JSON(), nullable=False),
            sa.Column("source_refs", sa.JSON(), nullable=False),
            sa.Column("merge_log", sa.JSON(), nullable=False),
            sa.Column("degree", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("community_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for name, columns, unique in (
            ("ix_kg_entity_tenant_id", ["tenant_id"], False),
            ("ix_kg_entity_entity_type", ["entity_type"], False),
            ("ix_kg_entity_classification", ["classification"], False),
            ("ix_kg_entity_community_id", ["community_id"], False),
            ("ix_kg_entity_scope", ["tenant_id", "entity_type", "norm_key"], False),
        ):
            op.create_index(name, "kg_entity", columns, unique=unique)
    if "kg_relation" not in existing:
        op.create_table(
            "kg_relation",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
            sa.Column("department_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("classification", sa.String(16), nullable=False, server_default="internal"),
            sa.Column("relation_key", sa.String(64), nullable=False),
            sa.Column("source_key", sa.String(160), nullable=False, server_default=""),
            sa.Column("head_id", sa.Integer(), sa.ForeignKey("kg_entity.id"), nullable=False),
            sa.Column("tail_id", sa.Integer(), sa.ForeignKey("kg_entity.id"), nullable=False),
            sa.Column("relation_type", sa.String(64), nullable=False),
            sa.Column("evidence", sa.Text(), nullable=False, server_default=""),
            sa.Column("source_ref", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for name, columns, unique in (
            ("ix_kg_relation_tenant_id", ["tenant_id"], False),
            ("ix_kg_relation_relation_key", ["relation_key"], True),
            ("ix_kg_relation_source_key", ["source_key"], False),
            ("ix_kg_relation_head_id", ["head_id"], False),
            ("ix_kg_relation_tail_id", ["tail_id"], False),
            ("ix_kg_relation_relation_type", ["relation_type"], False),
            ("ix_kg_relation_classification", ["classification"], False),
        ):
            op.create_index(name, "kg_relation", columns, unique=unique)
    if "kg_community" not in existing:
        op.create_table(
            "kg_community",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
            sa.Column("classification", sa.String(16), nullable=False, server_default="internal"),
            sa.Column("domain", sa.String(32), nullable=False, server_default="policy"),
            sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("signature", sa.String(64), nullable=False, server_default=""),
            sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("entity_ids", sa.JSON(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("model", sa.String(128), nullable=False, server_default=""),
            sa.Column("source", sa.String(32), nullable=False, server_default="rule"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        for name, columns, unique in (
            ("ix_kg_community_tenant_id", ["tenant_id"], False),
            ("ix_kg_community_classification", ["classification"], False),
            ("ix_kg_community_domain", ["domain"], False),
            ("ix_kg_community_signature", ["signature"], False),
        ):
            op.create_index(name, "kg_community", columns, unique=unique)


def downgrade():
    for name in ("kg_relation", "kg_community", "kg_entity"):
        op.drop_table(name)
