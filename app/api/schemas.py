"""Response models: what the API promises to RETURN (the request model is Transaction).

Declaring responses explicitly gives correct OpenAPI docs at /docs and stops internal
columns (like the raw payload) from leaking out by accident.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SubmitResponse(BaseModel):
    transaction_id: str
    status: str


class TransactionStatusResponse(BaseModel):
    transaction_id: str
    status: str
    received_at: datetime
    risk_score: float | None = None    # None until the Day 5 worker scores it
    risk_band: str | None = None
    model_version: str | None = None
    scored_at: datetime | None = None


class HealthResponse(BaseModel):
    status: str      # "ok" or "degraded"
    database: str
    kafka: str


# ---------------- Day 6: review queue ----------------

class ReviewCaseResponse(BaseModel):
    """Everything an analyst needs to decide, in ONE response (no second request per case)."""

    transaction_id: str
    status: str
    risk_score: float
    risk_band: str | None
    model_version: str | None
    created_at: datetime
    account_id: str
    amount_minor: int
    merchant_category: str
    channel: str
    event_time: datetime
    features: dict | None          # the exact model inputs: "why was this flagged?"
    analyst: str | None = None
    note: str | None = None
    decided_at: datetime | None = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # same strictness as the Day 1 contract

    decision: Literal["confirmed_fraud", "legitimate"]
    analyst: str = Field(min_length=1, max_length=64)
    note: str | None = Field(default=None, max_length=500)


class FeedbackSummary(BaseModel):
    """Analyst decisions per model version: the model's real-world precision on alerts."""

    model_version: str
    open: int
    confirmed_fraud: int
    legitimate: int
    decided: int
    precision: float | None   # None until at least one case is decided
