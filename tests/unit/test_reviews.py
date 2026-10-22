"""Review queue API tests (SQLite + fake publisher, no Docker)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.main import create_app
from app.db.models import STATUS_SCORED, ReviewCase, TransactionRecord
from app.db.session import create_tables, make_session_factory
from tests.unit.test_api import FakePublisher

NOW = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_tables(engine)
    return make_session_factory(engine)


@pytest.fixture
def client(session_factory):
    app = create_app(session_factory=session_factory, publisher=FakePublisher())
    with TestClient(app) as c:
        yield c


def add_case(session_factory, txn_id: str, score: float) -> None:
    """A scored high-risk transaction with an open case, as the Day 5 worker leaves it."""
    payload = {"transaction_id": txn_id, "account_id": "acct_1", "device_id": "dev_1",
               "event_time": "2026-10-17T09:59:00Z", "amount_minor": 2_500_000, "currency": "INR",
               "merchant_category": "electronics", "channel": "online", "schema_version": 1}
    with session_factory() as s:
        s.add(TransactionRecord(transaction_id=txn_id, account_id="acct_1", payload=payload,
                                status=STATUS_SCORED, received_at=NOW, risk_score=score, risk_band="high",
                                model_version="fraud_model_v1", scored_at=NOW,
                                features={"is_new_device": 1.0}))
        s.add(ReviewCase(transaction_id=txn_id, status="open", risk_score=score,
                         created_at=NOW + timedelta(seconds=len(txn_id))))
        s.commit()


def decide(client, txn_id, decision="confirmed_fraud", analyst="asif"):
    return client.post(f"/reviews/{txn_id}/decision", json={"decision": decision, "analyst": analyst})


def test_queue_is_sorted_by_risk_and_explains_the_score(client, session_factory):
    add_case(session_factory, "txn_low", 0.4)
    add_case(session_factory, "txn_top", 0.97)
    cases = client.get("/reviews").json()
    assert [c["transaction_id"] for c in cases] == ["txn_top", "txn_low"]
    assert cases[0]["features"] == {"is_new_device": 1.0}  # the analyst sees WHY it was flagged
    assert cases[0]["amount_minor"] == 2_500_000


def test_decision_closes_the_case(client, session_factory):
    add_case(session_factory, "txn_1", 0.9)
    r = decide(client, "txn_1")
    assert r.status_code == 200 and r.json()["status"] == "confirmed_fraud" and r.json()["analyst"] == "asif"
    assert client.get("/reviews").json() == []                                   # gone from the open queue
    assert len(client.get("/reviews", params={"status": "confirmed_fraud"}).json()) == 1


def test_a_case_is_decided_only_once(client, session_factory):
    add_case(session_factory, "txn_1", 0.9)
    decide(client, "txn_1", "confirmed_fraud", "asif")
    r = decide(client, "txn_1", "legitimate", "ravi")  # second analyst, too late
    assert r.status_code == 409
    assert client.get("/reviews", params={"status": "confirmed_fraud"}).json()[0]["analyst"] == "asif"


def test_unknown_case_returns_404(client):
    assert decide(client, "txn_missing").status_code == 404


@pytest.mark.parametrize("body", [
    {"decision": "maybe", "analyst": "asif"},                         # not an allowed decision
    {"decision": "legitimate", "analyst": ""},                        # empty analyst
    {"decision": "legitimate", "analyst": "asif", "score": 1},        # unknown field
])
def test_invalid_decisions_are_rejected(client, session_factory, body):
    add_case(session_factory, "txn_1", 0.9)
    assert client.post("/reviews/txn_1/decision", json=body).status_code == 422


def test_invalid_status_filter_is_rejected(client):
    assert client.get("/reviews", params={"status": "everything"}).status_code == 422