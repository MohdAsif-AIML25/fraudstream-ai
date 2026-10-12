"""Unit tests for the transaction data contract.

Pattern: start from ONE valid payload, change ONE field per test,
and check that the change alone causes acceptance or rejection.
"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas import Transaction


def valid_payload(**overrides) -> dict:
    """Return a known-good transaction. Keyword args replace individual fields."""
    payload = {
        "transaction_id": "txn_10001",
        "account_id": "acct_501",
        "device_id": "device_77",
        "event_time": "2026-10-11T14:20:00Z",   # 'Z' means UTC
        "amount_minor": 2_500_000,               # ₹25,000
        "currency": "INR",
        "merchant_category": "electronics",
        "channel": "online",
    }
    payload.update(overrides)  # e.g. valid_payload(currency="USD") swaps one field
    return payload


# ---------- Valid cases ----------

def test_valid_transaction_is_accepted():
    txn = Transaction(**valid_payload())          # ** unpacks the dict into keyword arguments
    assert txn.amount_minor == 2_500_000
    assert txn.schema_version == 1                # default was filled in
    assert txn.event_time.utcoffset() == timedelta(0)  # stored as UTC


def test_ist_time_is_converted_to_utc():
    # 19:50 IST (+05:30) is the same instant as 14:20 UTC
    txn = Transaction(**valid_payload(event_time="2026-10-11T19:50:00+05:30"))
    assert txn.event_time == datetime(2026, 10, 11, 14, 20, tzinfo=timezone.utc)


def test_whitespace_in_ids_is_stripped():
    txn = Transaction(**valid_payload(account_id="  acct_501  "))
    assert txn.account_id == "acct_501"


# ---------- Invalid cases ----------

@pytest.mark.parametrize(          # runs the same test once per value in the list
    "bad_amount",
    [0, -100, 100_000_001, "2500000", 2500000.5, True],
)
def test_invalid_amounts_are_rejected(bad_amount):
    with pytest.raises(ValidationError):          # test passes ONLY if this error is raised
        Transaction(**valid_payload(amount_minor=bad_amount))


def test_wrong_currency_is_rejected():
    with pytest.raises(ValidationError):
        Transaction(**valid_payload(currency="USD"))


def test_naive_timestamp_is_rejected():
    # No 'Z' and no '+05:30' means the timezone is unknown
    with pytest.raises(ValidationError, match="timezone"):  # match= also checks the error message
        Transaction(**valid_payload(event_time="2026-10-11T14:20:00"))


def test_future_timestamp_is_rejected():
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    with pytest.raises(ValidationError, match="future"):
        Transaction(**valid_payload(event_time=future))


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        Transaction(**valid_payload(ammount_minor=500))  # deliberate typo: extra='forbid' catches it


def test_unknown_merchant_category_is_rejected():
    with pytest.raises(ValidationError):
        Transaction(**valid_payload(merchant_category="casino"))


@pytest.mark.parametrize("bad_id", ["", "acct 501", "acct@501", "a" * 65])
def test_invalid_account_ids_are_rejected(bad_id):
    with pytest.raises(ValidationError):
        Transaction(**valid_payload(account_id=bad_id))


def test_missing_required_field_is_rejected():
    payload = valid_payload()
    del payload["device_id"]
    with pytest.raises(ValidationError):
        Transaction(**payload)


def test_transaction_is_immutable():
    txn = Transaction(**valid_payload())
    with pytest.raises(ValidationError):   # frozen=True blocks assignment after creation
        txn.amount_minor = 1