"""行业情报聚合表：迁移职责移交 Java Flyway（V1__baseline.sql）。

情报聚合表的唯一 owner 已裁定为 Java（source_config / collected_article /
article_cluster / intelligence_report / collection_task_log）。本迁移保留为空操作
以保证历史链条不断，Python 侧不再创建或变更这些表。

Revision ID: 4c1_intelligence_aggregation
Revises: 2a4f_policy_qa
"""
from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401


revision = "4c1_intelligence_aggregation"
down_revision = "2a4f_policy_qa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 表结构由 Java Flyway 管理，此处不再建表。
    pass


def downgrade() -> None:
    pass
