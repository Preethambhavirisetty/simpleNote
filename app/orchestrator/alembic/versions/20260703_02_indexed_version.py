"""Track which note version each indexed document reflects.

The reconciliation task compares agent_documents.indexed_version against
notes.version to find notes whose ingestion was lost or superseded. Existing
rows default to -1 ("version unknown"), which makes them eligible for one
re-ingestion pass that backfills the real value.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260703_02"
down_revision = "20260614_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_documents",
        sa.Column("indexed_version", sa.Integer(), nullable=False, server_default="-1"),
    )


def downgrade() -> None:
    op.drop_column("agent_documents", "indexed_version")
