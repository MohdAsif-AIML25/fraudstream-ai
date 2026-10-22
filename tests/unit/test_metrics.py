"""Monitoring tests: the numbers Grafana will show must actually move.

prometheus_client keeps ONE global registry, so tests compare a value BEFORE and AFTER
an action instead of expecting an absolute number.
"""

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.main import create_app
from app.db.session import create_tables, make_session_factory
from app.worker.consumer import ScoringWorker
from app.worker.processor import Outcome, ProcessResult
from app.models.scorer import ScoreResult
from tests.unit.test_api import FakePublisher, body
from tests.unit.test_worker import FakeConsumer, FakeDLQ, FakeMessage, FixedProcessor


def value(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_tables(engine)
    with TestClient(create_app(make_session_factory(engine), FakePublisher())) as c:
        yield c


def test_metrics_endpoint_speaks_prometheus_format(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert "fraudstream_http_requests_total" in r.text


def test_submissions_are_counted_by_result(client):
    before = value("fraudstream_transactions_submitted_total", result="accepted")
    before_dup = value("fraudstream_transactions_submitted_total", result="duplicate")
    client.post("/transactions", json=body())
    client.post("/transactions", json=body())  # retry -> duplicate
    assert value("fraudstream_transactions_submitted_total", result="accepted") == before + 1
    assert value("fraudstream_transactions_submitted_total", result="duplicate") == before_dup + 1


def test_route_label_uses_the_template_not_the_id(client):
    template = "/transactions/{transaction_id}"
    before = value("fraudstream_http_requests_total", method="GET", route=template, status="404")
    client.get("/transactions/txn_does_not_exist")
    assert value("fraudstream_http_requests_total", method="GET", route=template, status="404") == before + 1
    # No time series was created for the raw ID (that would be unbounded cardinality).
    assert value("fraudstream_http_requests_total", method="GET",
                 route="/transactions/txn_does_not_exist", status="404") == 0


def test_validation_errors_are_visible(client):
    before = value("fraudstream_http_requests_total", method="POST", route="/transactions", status="422")
    client.post("/transactions", json=body(amount_minor=-1))
    assert value("fraudstream_http_requests_total", method="POST", route="/transactions", status="422") == before + 1


def test_worker_records_outcome_band_score_and_queue_time():
    result = ProcessResult(Outcome.SCORED, "txn_1", ScoreResult(0.93, "high", "v1"), queue_seconds=0.4)
    log: list = []
    worker = ScoringWorker(FakeConsumer(log), FixedProcessor(result, log), FakeDLQ(log))

    before = {
        "scored": value("fraudstream_worker_messages_total", outcome="scored"),
        "high": value("fraudstream_risk_band_total", band="high"),
        "scores": value("fraudstream_risk_score_count"),
        "queue_fast": value("fraudstream_queue_to_score_seconds_bucket", le="0.5"),
    }
    worker.handle(FakeMessage(b"{}"))

    assert value("fraudstream_worker_messages_total", outcome="scored") == before["scored"] + 1
    assert value("fraudstream_risk_band_total", band="high") == before["high"] + 1
    assert value("fraudstream_risk_score_count") == before["scores"] + 1
    assert value("fraudstream_queue_to_score_seconds_bucket", le="0.5") == before["queue_fast"] + 1


def test_dead_letters_are_counted():
    log: list = []
    worker = ScoringWorker(FakeConsumer(log), FixedProcessor(ProcessResult(Outcome.DEAD_LETTER, reason="x"), log),
                           FakeDLQ(log))
    before = value("fraudstream_worker_messages_total", outcome="dead_letter")
    worker.handle(FakeMessage(b"bad"))
    assert value("fraudstream_worker_messages_total", outcome="dead_letter") == before + 1


def test_labelled_counters_exist_at_zero_before_anything_happens():
    """increase() needs an earlier sample: a series must exist BEFORE its first event."""
    from prometheus_client import generate_latest
    text = generate_latest().decode()
    for line in ('fraudstream_worker_messages_total{outcome="dead_letter"}',
                 'fraudstream_risk_band_total{band="high"}',
                 'fraudstream_review_decisions_total{decision="confirmed_fraud"}',
                 'fraudstream_transactions_submitted_total{result="kafka_unavailable"}'):
        assert line in text