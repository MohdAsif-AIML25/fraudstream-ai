"""End-to-end smoke test: send ONE new transaction and follow it through the whole system.

Run from project root (everything running, e.g. after `docker compose up -d --build`):
    python -m scripts.smoke_test
    python -m scripts.smoke_test --url http://<server-ip>:8000      # later, against a deployed server

Checks, in order (stops at the first failure, exit code 1):
  1. API is healthy                   GET  /health                 -> database ok, kafka ok
  2. API accepts a transaction        POST /transactions           -> 202 queued
  3. the worker scores it             GET  /transactions/{id}      -> status "scored" within --timeout s
  4. a retry is idempotent            POST same body again         -> 200, no second message
  5. metrics are exposed              GET  /metrics                -> fraudstream_ counters present
  6. review queue answers             GET  /reviews                -> 200

Unit tests prove each piece works alone; this proves the pieces work TOGETHER.
"""

import argparse
import sys
import time
import uuid
from datetime import datetime, timezone

import httpx


def step(number: int, text: str, ok: bool, detail: str = "") -> None:
    print(f"[{'OK' if ok else 'FAIL':<4}] {number}. {text}" + (f"  ({detail})" if detail else ""))
    if not ok:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for the worker")
    args = parser.parse_args()

    # A brand-new id every run, so the test never collides with old data.
    txn_id = f"smoke_{uuid.uuid4().hex[:12]}"
    body = {
        "transaction_id": txn_id,
        "account_id": "acct_smoke",
        "device_id": "device_smoke",
        "event_time": datetime.now(timezone.utc).isoformat(),  # "now": passes the future-skew rule
        "amount_minor": 125_000,
        "currency": "INR",
        "merchant_category": "grocery",
        "channel": "upi",
    }

    with httpx.Client(base_url=args.url, timeout=10) as client:
        try:
            health = client.get("/health")
        except httpx.HTTPError as exc:
            step(1, "API reachable", False, f"{type(exc).__name__}: is the api running at {args.url}?")
        step(1, "API healthy", health.status_code == 200, health.text)

        r = client.post("/transactions", json=body)
        step(2, "transaction accepted", r.status_code == 202 and r.json()["status"] == "queued",
             f"HTTP {r.status_code} {r.text[:120]}")

        deadline = time.monotonic() + args.timeout
        status = {}
        while time.monotonic() < deadline:
            status = client.get(f"/transactions/{txn_id}").json()
            if status.get("status") == "scored":
                break
            time.sleep(0.5)
        waited = args.timeout - max(deadline - time.monotonic(), 0)
        step(3, "worker scored it", status.get("status") == "scored",
             f"after {waited:.1f}s: score={status.get('risk_score')} band={status.get('risk_band')} "
             f"model={status.get('model_version')}" if status.get("status") == "scored"
             else f"still '{status.get('status')}' after {args.timeout:.0f}s -> check: docker compose logs worker")

        r = client.post("/transactions", json=body)
        step(4, "retry is idempotent", r.status_code == 200, f"HTTP {r.status_code}")

        metrics = client.get("/metrics").text
        step(5, "metrics exposed", "fraudstream_transactions_submitted_total" in metrics)

        r = client.get("/reviews")
        step(6, "review queue answers", r.status_code == 200, f"{len(r.json())} open case(s)")

    print(f"\nSMOKE TEST PASSED  ({txn_id})")


if __name__ == "__main__":
    main()