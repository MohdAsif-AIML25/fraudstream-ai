"""Worker logic tests: SQLite (database) + fakeredis (feature store) + stub model.

Each test is one real situation the worker meets in production.
"""

from datetime import datetime, timezone

import fakeredis
import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from app.db.models import STATUS_QUEUED, STATUS_SCORED, ReviewCase, TransactionRecord
from app.db.session import create_tables, make_session_factory
from app.features.online import RedisFeatureStore
from app.models.columns import MODEL_COLUMNS
from app.models.scorer import Scorer
from app.schemas import Transaction
from app.streaming.messages import encode_transaction
from app.worker.processor import Outcome, TransactionProcessor, to_event


class AmountModel:
    """Stub: big amounts look like fraud. Lets us force each risk band on purpose."""

    def predict_proba(self, X):
        p = 0.95 if X.loc[0, "amount_minor"] >= 1_000_000 else 0.01
        return np.array([[1 - p, p]])


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_tables(engine)
    return make_session_factory(engine)


@pytest.fixture
def store():
    return RedisFeatureStore(fakeredis.FakeRedis())


@pytest.fixture
def processor(session_factory, store):
    scorer = Scorer(AmountModel(), {"feature_columns": MODEL_COLUMNS, "model_version": "test_v1",
                                    "thresholds": {"high": 0.8, "medium": 0.3}})
    return TransactionProcessor(session_factory, store, scorer)


def make_txn(txn_id="txn_1", amount=50_000, time="2026-10-11T10:00:00Z") -> Transaction:
    return Transaction(transaction_id=txn_id, account_id="acct_501", device_id="device_A",
                       event_time=time, amount_minor=amount, currency="INR",
                       merchant_category="grocery", channel="upi")


def probe(time: str):
    """A hypothetical next event, used only to READ the account's history."""
    return to_event(make_txn("txn_probe", time=time))


def queue(session_factory, txn: Transaction) -> bytes:
    """What the Day 4 API does: save the row as 'queued', then the message is in Kafka."""
    with session_factory() as s:
        s.add(TransactionRecord(transaction_id=txn.transaction_id, account_id=txn.account_id,
                                payload=txn.model_dump(mode="json"), status=STATUS_QUEUED,
                                received_at=datetime.now(timezone.utc)))
        s.commit()
    return encode_transaction(txn)


def test_scores_and_saves_features(processor, session_factory):
    result = processor.process(queue(session_factory, make_txn()))
    assert result.outcome is Outcome.SCORED
    with session_factory() as s:
        row = s.get(TransactionRecord, "txn_1")
        assert row.status == STATUS_SCORED and row.risk_band == "low" and row.model_version == "test_v1"
        assert row.features["history_available"] == 0  # first transaction of the account
        assert s.get(ReviewCase, "txn_1") is None       # low risk -> no review case


def test_high_risk_opens_a_review_case(processor, session_factory):
    processor.process(queue(session_factory, make_txn(amount=2_500_000)))
    with session_factory() as s:
        case = s.get(ReviewCase, "txn_1")
        assert case is not None and case.status == "open" and case.risk_score == pytest.approx(0.95)


def test_second_transaction_sees_the_first(processor, session_factory):
    processor.process(queue(session_factory, make_txn("txn_1", time="2026-10-11T10:00:00Z")))
    result = processor.process(queue(session_factory, make_txn("txn_2", time="2026-10-11T10:02:00Z")))
    assert result.features["prior_txn_count_5m"] == 1
    assert result.features["seconds_since_previous_txn"] == 120


def test_redelivery_is_not_scored_twice(processor, session_factory, store):
    raw = queue(session_factory, make_txn())
    processor.process(raw)
    result = processor.process(raw)  # Kafka delivers the same message again
    assert result.outcome is Outcome.DUPLICATE
    later = store.features_for("acct_501", probe("2026-10-11T10:01:00Z"))
    assert later["prior_txn_count_5m"] == 1  # history counted the event ONCE


def test_crash_between_db_commit_and_redis_is_repaired(processor, session_factory, store):
    raw = queue(session_factory, make_txn())
    processor.process(raw)
    store._redis.flushall()                    # simulate: DB says scored, Redis never got the event
    assert processor.process(raw).outcome is Outcome.DUPLICATE
    assert store.features_for("acct_501", probe("2026-10-11T10:01:00Z"))["prior_txn_count_5m"] == 1


def test_invalid_bytes_go_to_dead_letter(processor):
    result = processor.process(b"{not json")
    assert result.outcome is Outcome.DEAD_LETTER and "invalid message" in result.reason


def test_unknown_transaction_goes_to_dead_letter(processor):
    result = processor.process(encode_transaction(make_txn("txn_ghost")))  # never saved by the API
    assert result.outcome is Outcome.DEAD_LETTER and result.reason == "transaction not in database"


def test_only_one_review_case_per_transaction(processor, session_factory):
    processor.process(queue(session_factory, make_txn(amount=2_500_000)))
    with session_factory() as s:
        assert len(s.scalars(select(ReviewCase)).all()) == 1