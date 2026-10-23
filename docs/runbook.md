# Runbook — what to do when an alert fires

Alerts are defined in [`infra/prometheus/alerts.yml`](../infra/prometheus/alerts.yml) and visible at
http://localhost:9090/alerts. All commands run from the project root (on EC2: inside `fraudstream-ai/`).

First look for any alert:

```bash
docker compose ps -a                 # which service is not "running" / "healthy"?
docker compose logs --tail 100 <service>
```

## FraudstreamWorkerDown (critical)

**Meaning:** Prometheus cannot scrape the worker for 1 minute. Transactions are accepted and queued in
Kafka, but nobody scores them. Nothing is lost: Kafka keeps them until the worker is back.

1. `docker compose logs --tail 100 worker`
2. Common causes:
   - `model missing` / `ModelContractError` → `artifacts/fraud_model_v1.joblib` is missing or does not
     match `artifacts_meta/fraud_model_v1.json`. Copy the right model, then `docker compose up -d worker`.
   - `Redis is not reachable` → `docker compose ps redis`, restart it.
   - Postgres errors → check `docker compose ps postgres`. The worker crashes on purpose instead of
     skipping messages; it resumes from the last committed offset after a restart.
3. After the fix, the backlog drains on its own. Watch *Worker throughput* in Grafana.

## FraudstreamApiDown (critical)

**Meaning:** the API has not answered `/metrics` for 1 minute. Clients cannot submit transactions.

1. `docker compose logs --tail 100 api migrate`
2. If `migrate` failed, the API never starts: fix the database/migration error, then `docker compose up -d`.
3. `curl -s localhost:8000/health` shows whether the database or Kafka is the problem.

## FraudstreamApiErrorRateHigh (critical)

**Meaning:** more than 5 % of requests returned 5xx for 5 minutes.

- **503 on `POST /transactions`** = Kafka unavailable. Rows are kept as `received`; client retries
  publish them. Check `docker compose ps kafka` and `logs kafka`.
- **500** = a bug. Find the stack trace in `docker compose logs api`.

## FraudstreamDeadLetters (warning)

**Meaning:** the worker parked at least one message in `transactions.dlq` in the last 5 minutes.

1. `docker compose exec api python -m scripts.inspect_dlq` (read-only) shows each message.
2. `invalid message` → a producer is breaking the [data contract](data_contract.md); fix the producer.
   `transaction not in database` → something published to Kafka without going through the API.
3. Dead letters are never retried automatically; replay them only after fixing the cause.

## FraudstreamScoringSlow (warning)

**Meaning:** p95 time from API acceptance to saved score is above 5 s: the worker is falling behind.

1. Grafana → *Acceptance to score* and *Worker throughput*. A sudden traffic spike or slow Postgres?
2. Scale out: the topic has 3 partitions, so up to 3 workers share the load:
   `docker compose up -d --scale worker=3` (remove the fixed `8001` host port first, or only one can bind it).

## FraudstreamHighRiskRateAbnormal (warning, ML alert)

**Meaning:** more than 6 % of traffic is scored *high* for 10 minutes; thresholds were chosen for ~2 %.
The service is healthy, but the **model's output** is not what it was trained for.

1. Grafana → *Score distribution* and *High-risk rate*. Sudden jump or slow drift?
2. Sudden jump → likely a data bug (e.g. amounts sent in rupees instead of paise, a new device-id
   format making every device "new") or a real attack. Inspect recent cases in the review dashboard.
3. Slow drift → traffic has changed since training. Check *Precision on reviewed cases*; if it falls,
   retrain with the analyst-labelled cases and re-pick thresholds (`scripts/select_model.py`).
4. Short-term protection: analysts' queue is the bottleneck, so tell the review team before the
   queue grows.
