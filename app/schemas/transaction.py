"""Data contract for an incoming transaction event (schema version 1).

Every component (API, Kafka producer, worker) uses this model, so they all
agree on what a valid transaction looks like.
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1

# Upper sanity limit: 100,000,000 paise = ₹10,00,000. Larger values are likely input errors.
MAX_AMOUNT_MINOR = 100_000_000

# Allowed clock difference between the sender's clock and ours.
MAX_FUTURE_SKEW = timedelta(minutes=5)

# IDs: 1–64 characters, letters/digits/underscore/hyphen only. Blocks spaces and odd characters.
ID_PATTERN = r"^[A-Za-z0-9_\-]{1,64}$"


class MerchantCategory(str, Enum):
    """Closed list of categories. 'str' mixin makes values serialize as plain strings in JSON."""

    GROCERY = "grocery"
    ELECTRONICS = "electronics"
    TRAVEL = "travel"
    FOOD = "food"
    FASHION = "fashion"
    UTILITIES = "utilities"
    OTHER = "other"


class Channel(str, Enum):
    """How the payment was made."""

    ONLINE = "online"
    POS = "pos"   # card swiped at a shop terminal (point of sale)
    ATM = "atm"
    UPI = "upi"


class Transaction(BaseModel):
    """One transaction event as received from a client or simulator."""

    model_config = ConfigDict(
        extra="forbid",              # unknown fields cause an error (catches typos like 'ammount_minor')
        frozen=True,                 # immutable after creation: no component can silently change it
        str_strip_whitespace=True,   # " acct_501 " becomes "acct_501"
    )

    # Literal[1] = the ONLY accepted value is 1. Version 2 would get a new model.
    schema_version: Literal[1] = SCHEMA_VERSION

    transaction_id: str = Field(pattern=ID_PATTERN, description="Unique ID; used later for idempotency")
    account_id: str = Field(pattern=ID_PATTERN, description="Becomes the Kafka message key on Day 4")
    device_id: str = Field(pattern=ID_PATTERN)

    event_time: datetime  # when the transaction HAPPENED (not when we received it)

    amount_minor: int = Field(
        gt=0,                   # must be greater than 0
        le=MAX_AMOUNT_MINOR,    # less than or equal to the sanity limit
        strict=True,            # reject "2500000" (string) and 2500000.5 (float): only real integers
        description="Amount in paise. 2500000 = ₹25,000",
    )

    currency: Literal["INR"]  # single currency in version 1 (a scope decision from Stage 1)

    merchant_category: MerchantCategory  # value must match one Enum member
    channel: Channel

    @field_validator("event_time")
    @classmethod
    def validate_event_time(cls, value: datetime) -> datetime:
        """Require a timezone, normalize to UTC, and reject times too far in the future."""

        # A 'naive' datetime has no timezone. We can't know if 14:20 is IST or UTC, so reject it.
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event_time must include a timezone, e.g. '2026-10-11T14:20:00Z'")

        # Convert any offset to UTC: 19:50+05:30 becomes 14:20+00:00. Same instant, one standard.
        value_utc = value.astimezone(timezone.utc)

        # A transaction can't happen in the future. A small skew is allowed for clock differences.
        if value_utc > datetime.now(timezone.utc) + MAX_FUTURE_SKEW:
            raise ValueError("event_time is too far in the future")

        return value_utc  