"""Database tables (SQLAlchemy 2.0 ORM).

One row per transaction. The row records the LIFECYCLE of an event:
    received -> queued -> scored      (scored arrives on Day 5)
Storing the status lets GET /transactions/{id} answer "where is my transaction?"
"""

from datetime import datetime
from sqlalchemy import JSON,DateTime,Float,String 
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column 

STATUS_RECEIVED= "received"
STATUS_QUEUED= "queued"
STATUS_SCORED= "scored"

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
