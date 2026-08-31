"""material chunks

Revision ID: 9b7a0d3f4c21
Revises: 3ef823c5b062
Create Date: 2026-08-20 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "9b7a0d3f4c21"
down_revision = "3ef823c5b062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "material_chunk",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["material_id"], ["reference_material.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_material_chunk_material_id"), "material_chunk", ["material_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_material_chunk_material_id"), table_name="material_chunk")
    op.drop_table("material_chunk")
