"""G9：新增 LTR 排序模型表（ranking_model）。

与 `app/agent/platform_models.py::RankingModelRecord` 字段保持一致：
权重 / 指标 / 数据集摘要全部落库，激活与退役可追溯、可回滚；
本表不含知识正文，因此不参与 `install_data_isolation`，按 domain + tenant_id 归属。
"""
from alembic import op
import sqlalchemy as sa

revision = "9g8_ranking_model"
down_revision = "9f7_model_routing"
branch_labels = None
depends_on = None


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "ranking_model" in existing:
        return
    op.create_table(
        "ranking_model",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("domain", sa.String(32), nullable=False, server_default="policy"),
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="shadow"),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("weights", sa.JSON(), nullable=False),
        sa.Column("bias", sa.Float(), nullable=False, server_default="0"),
        sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("positives", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("dataset_digest", sa.String(64), nullable=False, server_default=""),
        sa.Column("notes", sa.String(500), nullable=False, server_default=""),
        sa.Column("trained_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    for name, columns, unique in (
        ("ix_ranking_model_domain", ["domain"], False),
        ("ix_ranking_model_tenant_id", ["tenant_id"], False),
        ("ix_ranking_model_status", ["status"], False),
        ("ix_ranking_model_scope_status", ["domain", "tenant_id", "status"], False),
    ):
        op.create_index(name, "ranking_model", columns, unique=unique)


def downgrade():
    op.drop_table("ranking_model")