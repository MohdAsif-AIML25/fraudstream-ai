"""API tests with an in-memory SQLite database and a fake Kafka publisher.

No Docker needed: create_app() lets us inject replacements (dependency injection).
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.main import create_app
from app.db.session import create_tables, make_session_factory
from app.streaming.producer import PublishError


class FakePublisher:
    """Records messages instead of sending them. fail=True simulates Kafka being down."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, bytes, bytes]] = []
        self.fail = False

    def publish(self, topic: str, key: bytes, value: bytes) -> None:
        if self.fail:
            raise PublishError("kafka down")
        self.messages.append((topic, key, value))

    def healthy(self) -> bool:
        return not self.fail

    def close(self) -> None:
        pass


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def client(publisher):
    # StaticPool + check_same_thread=False: every session shares ONE in-memory database.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_tables(engine)
    app = create_app(session_factory=make_session_factory(engine), publisher=publisher)
    with TestClient(app) as c:  # 'with' runs the lifespan (startup/shutdown)
        yield c


def body(**overrides) -> dict:
    payload = {
        "transaction_id": "txn_10001", "account_id": "acct_501", "device_id": "device_77",
        "event_time": "2026-10-11T14:20:00Z", "amount_minor": 2_500_000,
        "currency": "INR", "merchant_category": "electronics", "channel": "online",
    }
    payload.update(overrides)
    return payload


def test_valid_transaction_is_accepted_and_published(client, publisher):
    r = client.post("/transactions", json=body())
    assert r.status_code == 202
    assert r.json() == {"transaction_id": "txn_10001", "status": "queued"}
    assert len(publisher.messages) == 1
    topic, key, _ = publisher.messages[0]
    assert topic == "transactions.raw" and key == b"acct_501"


def test_invalid_transaction_returns_422_and_is_not_published(client, publisher):
    r = client.post("/transactions", json=body(amount_minor=-5))
    assert r.status_code == 422
    assert publisher.messages == []
    assert client.get("/transactions/txn_10001").status_code == 404  # nothing stored either


def test_duplicate_is_idempotent(client, publisher):
    client.post("/transactions", json=body())
    r = client.post("/transactions", json=body())       # client retries the same request
    assert r.status_code == 200
    assert r.json()["status"] == "queued"
    assert len(publisher.messages) == 1                   # NOT published twice


def test_same_id_with_different_data_is_a_conflict(client):
    client.post("/transactions", json=body())
    r = client.post("/transactions", json=body(amount_minor=999))
    assert r.status_code == 409


def test_kafka_outage_returns_503_and_retry_publishes(client, publisher):
    publisher.fail = True
    r = client.post("/transactions", json=body())
    assert r.status_code == 503
    assert client.get("/transactions/txn_10001").json()["status"] == "received"  # saved, not lost

    publisher.fail = False
    r = client.post("/transactions", json=body())        # client retries after the outage
    assert r.status_code == 202
    assert r.json()["status"] == "queued"
    assert len(publisher.messages) == 1


def test_get_status_of_queued_transaction(client):
    client.post("/transactions", json=body())
    data = client.get("/transactions/txn_10001").json()
    assert data["status"] == "queued"
    assert data["risk_score"] is None                     # scoring happens on Day 5


def test_unknown_transaction_returns_404(client):
    assert client.get("/transactions/nope").status_code == 404


def test_health_reports_kafka_down(client, publisher):
    assert client.get("/health").json() == {"status": "ok", "database": "ok", "kafka": "ok"}
    publisher.fail = True
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["kafka"] == "down"