"""Create the transactions table (exactly what  create_all produced).

This baseline lets an EXISTING  database join Alembic without losing data:
    alembic stamp 0001      # "this database already has 0001", nothing is executed
    alembic upgrade head    # then apply only the newer migrations
A brand-new database just runs:  alembic upgrade head

Revision ID: 0001
Revises:
Create Date: 2026-10-17
"""

import sqlalchemy as sa 
from alembic import op 

revision="0001"
down_revision=None 
branch_labels=None 
depends_on=None 


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("transaction_id", sa.String(64), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("risk_band", sa.String(8), nullable=True),
        sa.Column("model_version", sa.String(32), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_transactions_account_id","transactions",["account_id"])

def downgrade() ->None:
    op.drop_index("ix_transactions_account_id",table_name="transactions")
    op.drop_table("transactions")
    