"""Every Prometheus metric of FraudStream, defined in ONE place.

Prometheus PULLS: every 15 s it fetches /metrics from the API (:8000) and the worker (:8001).
Our code only increments numbers in memory; Prometheus stores the history, Grafana draws it.

Metric types used here:
  Counter   only goes up (total requests). Grafana shows rate() = "per second".
  Histogram counts observations into buckets (latency, scores) -> percentiles like p95.

Naming rules (Prometheus convention): <app>_<what>_<unit>, counters end in _total,
times are in SECONDS. Labels must have FEW possible values: a label like transaction_id
would create one time series per transaction and overload Prometheus ("high cardinality").
"""

from prometheus_client import Counter, Histogram

# ---------------- API ----------------

HTTP_REQUESTS = Counter(
    "fraudstream_http_requests_total", "HTTP requests handled by the API",
    ["method", "route", "status"],  # route = the TEMPLATE "/transactions/{transaction_id}", not the real ID
)
HTTP_LATENCY = Histogram(
    "fraudstream_http_request_duration_seconds", "Time to answer an HTTP request",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
SUBMISSIONS = Counter(
    "fraudstream_transactions_submitted_total", "Submission results",
    ["result"],  # accepted | duplicate | conflict | kafka_unavailable
)
REVIEW_DECISIONS = Counter(
    "fraudstream_review_decisions_total", "Analyst decisions on review cases",
    ["decision"],  # confirmed_fraud | legitimate
)

# ---------------- worker ----------------

WORKER_MESSAGES = Counter(
    "fraudstream_worker_messages_total", "Kafka messages handled by the worker",
    ["outcome"],  # scored | duplicate | dead_letter
)
WORKER_PROCESSING = Histogram(
    "fraudstream_worker_processing_seconds", "Time to process one message (features + model + DB)",
    buckets=(0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
)
QUEUE_TO_SCORE = Histogram(
    "fraudstream_queue_to_score_seconds", "From API acceptance (received_at) to score saved",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
RISK_SCORE = Histogram(
    "fraudstream_risk_score", "Distribution of model scores (detects drift)",
    buckets=(0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.0),
)
RISK_BANDS = Counter(
    "fraudstream_risk_band_total", "Scored transactions per risk band",
    ["band"],  # low | medium | high
)


def _start_at_zero() -> None:
    """Create every known label combination with value 0 at startup.

    Why? A counter that APPEARS for the first time already at 1 looks like "no change" to
    increase()/rate(), because Prometheus has no earlier sample to compare with. Without this,
    the FIRST dead letter after a restart would never trigger the alert. (Found in the Day 6
    end-to-end test: one poison message, alert stayed silent.)
    """
    for outcome in ("scored", "duplicate", "dead_letter"):
        WORKER_MESSAGES.labels(outcome=outcome)
    for band in ("low", "medium", "high"):
        RISK_BANDS.labels(band=band)
    for result in ("accepted", "duplicate", "conflict", "kafka_unavailable"):
        SUBMISSIONS.labels(result=result)
    for decision in ("confirmed_fraud", "legitimate"):
        REVIEW_DECISIONS.labels(decision=decision)


_start_at_zero()