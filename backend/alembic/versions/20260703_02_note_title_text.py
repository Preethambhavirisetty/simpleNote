"""Widen notes.title to TEXT so encrypted titles fit.

Encrypted note fields are stored as an `enc:v..:<base64>` token that is longer than the
plaintext, so title can no longer be capped at 500 chars.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260703_02"
down_revision = "20260703_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "notes",
        "title",
        type_=sa.Text(),
        existing_type=sa.String(length=500),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "notes",
        "title",
        type_=sa.String(length=500),
        existing_type=sa.Text(),
        existing_nullable=False,
    )
