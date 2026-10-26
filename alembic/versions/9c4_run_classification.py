"""Keep historical run payloads private until their classification is reviewed."""
from alembic import op
import sqlalchemy as sa

revision = "9c4_run_classification"
down_revision = "9b3_ai_derived"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_run", sa.Column(
        "classification", sa.String(16), nullable=False, server_default="restricted",
    ))


def downgrade():
    op.drop_column("agent_run", "classification")
