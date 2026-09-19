"""add risk_data column to risk_reports

Revision ID: 0002_add_risk_data
Revises: 0001_initial
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa

revision = "0002_add_risk_data"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("risk_reports") as batch_op:
        batch_op.add_column(sa.Column("risk_data", sa.JSON(), nullable=False, server_default="{}"))
    with op.batch_alter_table("risk_reports") as batch_op:
        batch_op.alter_column("risk_data", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("risk_reports") as batch_op:
        batch_op.drop_column("risk_data")
