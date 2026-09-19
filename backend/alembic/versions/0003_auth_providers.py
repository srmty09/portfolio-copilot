"""nullable password, google oauth, password reset tokens

Revision ID: 0003_auth_providers
Revises: 0002_add_risk_data
Create Date: 2026-09-18

"""
from alembic import op
import sqlalchemy as sa

revision = "0003_auth_providers"
down_revision = "0002_add_risk_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("hashed_password", existing_type=sa.String(), nullable=True)
        batch_op.add_column(sa.Column("auth_provider", sa.String(), nullable=False, server_default="local"))
        batch_op.add_column(sa.Column("google_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("reset_token", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("reset_token_expires_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("auth_provider", server_default=None)
        batch_op.create_index("ix_users_google_id", ["google_id"], unique=True)
        batch_op.create_index("ix_users_reset_token", ["reset_token"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_reset_token")
        batch_op.drop_index("ix_users_google_id")
        batch_op.drop_column("reset_token_expires_at")
        batch_op.drop_column("reset_token")
        batch_op.drop_column("google_id")
        batch_op.drop_column("auth_provider")
        # Only safe if no rows have a NULL hashed_password (i.e. no Google-only
        # accounts were created) -- an inherent limitation of downgrading this change.
        batch_op.alter_column("hashed_password", existing_type=sa.String(), nullable=False)
