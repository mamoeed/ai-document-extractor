"""processed_files table

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processed_files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.Text(), nullable=True),
        sa.Column("file_sha256", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("match_result", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False),
        sa.Column("human_reviewed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("human_corrected", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("ai_status", sa.Text(), nullable=True),
        sa.Column("ai_confidence_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("order_number", sa.Text(), nullable=True),
        sa.Column("customer_label", sa.Text(), nullable=True),
        sa.Column("customer_matched", sa.Boolean(), nullable=True),
        sa.Column("items_matched", sa.Integer(), nullable=True),
        sa.Column("items_total", sa.Integer(), nullable=True),
        sa.Column("issues", postgresql.JSONB(), nullable=True),
        sa.Column("extracted_json", postgresql.JSONB(), nullable=True),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("reviewed_json", postgresql.JSONB(), nullable=True),
        sa.Column("reviewed_result_json", postgresql.JSONB(), nullable=True),
        sa.Column("review_changes", postgresql.JSONB(), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extraction_method", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_processed_files_uploaded_at", "processed_files", ["uploaded_at"])


def downgrade() -> None:
    op.drop_index("ix_processed_files_uploaded_at", table_name="processed_files")
    op.drop_table("processed_files")
