"""Business logic of 'submit a transaction', kept OUT of the HTTP layer.

Why separate? The route only translates HTTP <-> Python. This function holds the rules,
so it is easy to test and could be reused (e.g. by a batch importer) without FastAPI.

Flow:   save row (received)  ->  publish to Kafka  ->  mark row queued
If Kafka fails, the row stays 'received'. A client RETRY then publishes it again,
so a temporary Kafka outage never loses an accepted transaction.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import STATUS_QUEUED, STATUS_RECEIVED, TransactionRecord
from app.schemas import Transaction
from app.streaming.messages import encode_transaction, message_key
from app.streaming.producer import Publisher
from app.streaming.topics import RAW_TOPIC


class PayloadConflict(Exception):
    """Same transaction_id was already received with DIFFERENT content."""


@dataclass
class SubmitResult:
    record: TransactionRecord
    created: bool  # True = newly published now; False = duplicate, nothing re-sent


def submit_transaction(session: Session, publisher: Publisher, txn: Transaction) -> SubmitResult:
    payload = txn.model_dump(mode="json")  # mode="json": datetime -> str, so it fits a JSON column
    record = session.get(TransactionRecord, txn.transaction_id)

    if record is not None:
        if record.payload != payload:
            raise PayloadConflict(txn.transaction_id)
        if record.status != STATUS_RECEIVED:
            # Already published earlier: a client retry must NOT create a second Kafka message.
            return SubmitResult(record, created=False)
        # status == received: an earlier attempt saved it but Kafka failed -> publish now.
    else:
        record = TransactionRecord(
            transaction_id=txn.transaction_id,
            account_id=txn.account_id,
            payload=payload,
            status=STATUS_RECEIVED,
            received_at=datetime.now(timezone.utc),
        )
        session.add(record)
        try:
            session.commit()  # commit BEFORE publishing: the event is durable even if Kafka is down
        except IntegrityError:
            # Two identical requests raced; the other one inserted first. Treat as duplicate.
            session.rollback()
            existing = session.get(TransactionRecord, txn.transaction_id)
            return SubmitResult(existing, created=False)

    publisher.publish(RAW_TOPIC, key=message_key(txn), value=encode_transaction(txn))  # may raise PublishError

    record.status = STATUS_QUEUED
    session.commit()
    return SubmitResult(record, created=True)