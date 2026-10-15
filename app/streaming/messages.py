"""How a Transaction is turned into Kafka bytes, and back.

Producer and consumer MUST agree on this format, so both use these two functions.
The message value is simply the data contract as JSON: the consumer re-validates it
with the same Transaction model, so a corrupted message is detected, not trusted.
"""

from app.schemas import Transaction


def encode_transaction(txn: Transaction) -> bytes:
    # model_dump_json: datetimes -> ISO strings, enums -> plain values ("online")
    return txn.model_dump_json().encode("utf-8")


def decode_transaction(raw: bytes) -> Transaction:
    # model_validate_json raises ValidationError on bad input -> the worker can send it to the DLQ
    return Transaction.model_validate_json(raw)


def message_key(txn: Transaction) -> bytes:
    """Kafka key = account_id. Same key -> same partition -> one account's events stay in order."""
    return txn.account_id.encode("utf-8")