"""Database tables (SQLAlchemy 2.0 ORM).

One row per transaction. The row records the LIFECYCLE of an event:
    received -> queued -> scored      (scored arrives on Day 5)
Storing the status lets GET /transactions/{id} answer "where is my transaction?"
"""

from datetime import datetime
from sqlalchemy import JSON,DateTime,Float,String,ForeignKey,Text 
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column 

# Status values, kept as constants so a typo becomes an import error, not a silent bug.
STATUS_RECEIVED = "received"  # saved in the database, NOT yet published to Kafka
STATUS_QUEUED = "queued"      # published to Kafka, waiting for the scoring worker
STATUS_SCORED = "scored"      # worker saved a risk score 

# Review case states 
REVIEW_OPEN = "open"                   # waiting for an analyst
REVIEW_CONFIRMED_FRAUD = "confirmed_fraud"
REVIEW_LEGITIMATE = "legitimate"



class Base(DeclarativeBase):
     """Parent class of every table; Base.metadata knows all tables (used by create_all)."""

class TransactionRecord(Base):
    __tablename__="transactions"

    transaction_id: Mapped[str]=mapped_column(String(64),primary_key=True)
    account_id: Mapped[str]=mapped_column(String(64),index=True)
    payload: Mapped[dict]=mapped_column(JSON)
    status: Mapped[str]=mapped_column(String(16),default=STATUS_RECEIVED)
    received_at: Mapped[datetime]=mapped_column(DateTime(timezone=True))

    # Filled by the worker on Day 5. Nullable: a queued transaction has no score yet.
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_band: Mapped[str | None] = mapped_column(String(8), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    features: Mapped[dict |None]=mapped_column(JSON,nullable=True)

class ReviewCase(Base):
    """A high-risk transaction waiting for a human decision.

    Separate table (not more columns on transactions) because a review has its OWN lifecycle,
    owner and timestamps. The analyst's decision later becomes a training label.
    """

    __tablename__="review_cases"
    # Same ID as the transaction: one case per transaction, enforced by the primary key.
    transaction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("transactions.transaction_id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), default=REVIEW_OPEN, index=True)  # index: "all open cases"
    risk_score: Mapped[float] = mapped_column(Float)  # copied so the queue can be sorted without a join
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Filled when an analyst decides (Day 6).
    analyst: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)