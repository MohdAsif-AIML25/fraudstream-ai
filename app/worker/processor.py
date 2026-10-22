"""What the worker does with ONE Kafka message. No Kafka code here on purpose:
the loop in consumer.py feeds bytes in, this module decides and acts. That keeps the
business logic testable with SQLite + fakeredis, without a broker.

For each message:
    1. decode + validate        bad bytes            -> DEAD_LETTER (never retried forever)
    2. find the DB row          unknown transaction  -> DEAD_LETTER
    3. already scored?          duplicate delivery   -> repair Redis, DUPLICATE
    4. features from Redis      (read BEFORE write: the event must not see itself)
    5. model score + band
    6. save score (+ open a review case if high)   -> one DB commit
    7. add the event to Redis   (AFTER the DB commit)

Why save to the DB BEFORE updating Redis?
    If we crash between 6 and 7, Kafka redelivers the message, step 3 sees "scored",
    and re-adds the event to Redis (add() is idempotent). Nothing is lost, nothing is doubled.
    The opposite order could leave Redis "ahead" of the DB.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import REVIEW_OPEN, STATUS_SCORED, ReviewCase, TransactionRecord
from app.features.compute import Event
from app.features.online import RedisFeatureStore
from app.models.scorer import ScoreResult, Scorer
from app.schemas import Transaction
from app.streaming.messages import decode_transaction


class Outcome(str, Enum):
    SCORED = "scored"
    DUPLICATE = "duplicate"
    DEAD_LETTER = "dead_letter"


@dataclass
class ProcessResult:
    outcome: Outcome
    transaction_id: str | None = None
    result: ScoreResult | None = None
    reason: str | None = None        # why it went to the DLQ (written to the worker log)
    features: dict = field(default_factory=dict)
    queue_seconds: float | None = None  # Day 6: API acceptance -> score saved (for monitoring)


def to_event(txn: Transaction) -> Event:
    return Event(event_time=txn.event_time, amount_minor=txn.amount_minor, device_id=txn.device_id)


class TransactionProcessor:
    def __init__(self, session_factory: sessionmaker, store: RedisFeatureStore, scorer: Scorer) -> None:
        self._session_factory = session_factory
        self._store = store
        self._scorer = scorer

    def process(self, raw: bytes) -> ProcessResult:
        # 1) Decode. A message that breaks the contract will NEVER succeed, so retrying is pointless.
        try:
            txn = decode_transaction(raw)
        except (ValidationError, ValueError, UnicodeDecodeError) as exc:
            return ProcessResult(Outcome.DEAD_LETTER, reason=f"invalid message: {type(exc).__name__}")

        event = to_event(txn)
        with self._session_factory() as session:  # 'with' closes the session even on errors
            record = session.get(TransactionRecord, txn.transaction_id)

            # 2) The API always saves before publishing, so a missing row means something is wrong upstream.
            if record is None:
                return ProcessResult(Outcome.DEAD_LETTER, txn.transaction_id, reason="transaction not in database")

            # 3) At-least-once delivery: we may see the same message twice.
            if record.status == STATUS_SCORED:
                self._store.add(txn.account_id, txn.transaction_id, event)  # repair Redis if a crash skipped step 7
                return ProcessResult(Outcome.DUPLICATE, txn.transaction_id)

            # 4) + 5)
            features = self._store.features_for(txn.account_id, event)
            result = self._scorer.score(txn, features)

            # 6) Save everything in ONE commit: score and review case appear together or not at all.
            scored_at = self._save(session, record, features, result)
            queue_seconds = (scored_at - _as_utc(record.received_at)).total_seconds()

        # 7) Only after the commit succeeded.
        self._store.add(txn.account_id, txn.transaction_id, event)
        return ProcessResult(Outcome.SCORED, txn.transaction_id, result, features=features,
                             queue_seconds=queue_seconds)

    @staticmethod
    def _save(session: Session, record: TransactionRecord, features: dict, result: ScoreResult) -> datetime:
        now = datetime.now(timezone.utc)
        record.status = STATUS_SCORED
        record.risk_score = result.score
        record.risk_band = result.band
        record.model_version = result.model_version
        record.scored_at = now
        record.features = features

        if result.band == "high":
            # session.merge: insert, or update if a case somehow exists already (keeps this step idempotent)
            session.merge(ReviewCase(transaction_id=record.transaction_id, status=REVIEW_OPEN,
                                     risk_score=result.score, created_at=now))
        session.commit()
        return now


def _as_utc(value: datetime) -> datetime:
    """Postgres returns timezone-aware datetimes; SQLite (tests) returns naive ones in UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)