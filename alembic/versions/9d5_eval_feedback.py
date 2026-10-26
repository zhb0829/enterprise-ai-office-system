"""G2 线上回流：qa_log 增加反馈、是否解决与运行关联字段。"""
from alembic import op
import sqlalchemy as sa

revision = "9d5_eval_feedback"
down_revision = "9c4_run_classification"
branch_labels = None
depends_on = None

_INDEXES = (
    ("ix_qa_log_tenant_id", ["tenant_id"]),
    ("ix_qa_log_user_id", ["user_id"]),
    ("ix_qa_log_run_id", ["run_id"]),
    ("ix_qa_log_feedback", ["feedback"]),
)


def upgrade():
    op.add_column("qa_log", sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"))
    op.add_column("qa_log", sa.Column("user_id", sa.String(64), nullable=False, server_default=sa.text("''")))
    op.add_column("qa_log", sa.Column("run_id", sa.String(64), nullable=False, server_default=sa.text("''")))
    op.add_column("qa_log", sa.Column("resolved", sa.Boolean(), nullable=True))
    op.add_column("qa_log", sa.Column("feedback_reason", sa.Text(), nullable=False, server_default=sa.text("''")))
    op.add_column("qa_log", sa.Column("feedback_user_id", sa.String(64), nullable=False, server_default=sa.text("''")))
    op.add_column("qa_log", sa.Column("feedback_at", sa.DateTime(), nullable=True))
    for name, columns in _INDEXES:
        op.create_index(name, "qa_log", columns)


def downgrade():
    for name, _ in reversed(_INDEXES):
        op.drop_index(name, table_name="qa_log")
    for column in (
        "feedback_at", "feedback_user_id", "feedback_reason",
        "resolved", "run_id", "user_id", "tenant_id",
    ):
        op.drop_column("qa_log", column)