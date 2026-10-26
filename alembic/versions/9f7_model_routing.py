"""G4：把模型分层路由决策落到 agent_run.routing，便于按 run 回溯。

历史行没有这列时默认 `{}`，读出侧按"未记录路由"处理（`app/services/model_router.py`
的决策只在开启路由后才产生，默认关闭时不产生任何决策）。
"""
from alembic import op
import sqlalchemy as sa

revision = "9f7_model_routing"
down_revision = "9e6_kg_tables"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("agent_run")}
    if "routing" not in existing:
        op.add_column("agent_run", sa.Column("routing", sa.JSON(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("agent_run", "routing")