"""Producer and consumer must agree on the message format."""

from app.schemas import Transaction
from app.streaming.messages import decode_transaction, encode_transaction, message_key

TXN = Transaction(
    transaction_id="txn_1", account_id="acct_501", device_id="device_77",
    event_time="2026-10-11T19:50:00+05:30", amount_minor=2_500_000,
    currency="INR", merchant_category="electronics", channel="online",
)


def test_encode_then_decode_returns_the_same_transaction():
    assert decode_transaction(encode_transaction(TXN)) == TXN


def test_key_is_account_id_so_one_account_stays_in_one_partition():
    assert message_key(TXN) == b"acct_501"


def test_encoded_time_is_utc():
    assert b"2026-10-11T14:20:00Z" in encode_transaction(TXN)  # IST input was normalized