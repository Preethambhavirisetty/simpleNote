"""Add a token version used to invalidate sessions after password changes."""

from alembic import op
import sqlalchemy as sa


revision = "20260928_03"
down_revision = "20260703_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("users", "auth_version", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "auth_version")
