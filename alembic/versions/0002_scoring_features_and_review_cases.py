""" Store the features used for scoring, and add the review queue.

- transactions.features : JSON, nullable -> old rows stay valid (adding a NOT NULL column
                          to a table with data would fail)
- review_cases          : one row per high-risk transaction

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("features", sa.JSON(), nullable=True))

    op.create_table(
        "review_cases",
        sa.Column("transaction_id", sa.String(64), sa.ForeignKey("transactions.transaction_id"),
                  primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("analyst", sa.String(64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_review_cases_status", "review_cases", ["status"])


def downgrade() -> None:
    # Every upgrade has a downgrade: if a release goes wrong you can step back one version.
    op.drop_index("ix_review_cases_status", table_name="review_cases")
    op.drop_table("review_cases")
    op.drop_column("transactions", "features")