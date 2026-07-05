"""Create retrieval artifact tables and add user timezone."""

from alembic import op
import sqlalchemy as sa


revision = "20260614_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("timezone", sa.Text(), nullable=False, server_default="UTC"),
    )
    op.create_table(
        "agent_documents",
        sa.Column("doc_id", sa.Text(), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("folder_id", sa.Text(), nullable=False),
        sa.Column("note_id", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("summary_generated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "timestamp_fallback",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_agent_documents_user_id", "agent_documents", ["user_id"])
    op.create_table(
        "agent_chunk_dates",
        sa.Column(
            "doc_id",
            sa.Text(),
            sa.ForeignKey("agent_documents.doc_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chunk_id", sa.Text(), primary_key=True),
        sa.Column("date_value", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("date_text", sa.Text(), primary_key=True),
        sa.Column("date_precision", sa.String(16), nullable=False),
        sa.Column("date_type", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "agent_skipped_chunks",
        sa.Column(
            "doc_id",
            sa.Text(),
            sa.ForeignKey("agent_documents.doc_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chunk_id", sa.Text(), primary_key=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embed_text", sa.Text(), nullable=False),
        sa.Column("prev_chunk_id", sa.Text()),
        sa.Column("next_chunk_id", sa.Text()),
        sa.Column("skip_reason", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_skipped_chunks")
    op.drop_table("agent_chunk_dates")
    op.drop_index("ix_agent_documents_user_id", table_name="agent_documents")
    op.drop_table("agent_documents")
    op.drop_column("users", "timezone")
