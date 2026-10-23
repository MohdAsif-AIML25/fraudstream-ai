"""Replay generated transactions into the running API, like a real client would.

Run from project root (API must be running):
    python -m scripts.replay --limit 50 --rate 5
    python -m scripts.replay --skip 50 --limit 500 --rate 20     # the NEXT 500, so nothing is a duplicate

--rate 5 = 5 transactions per second, our v1 load target from the project spec.
"""

import argparse
import time
from collections import Counter

import httpx
import pandas as pd

LABEL_COLUMNS = ["is_fraud", "fraud_scenario"]  # never sent: a real client doesn't know the label


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inp", default="data/raw/transactions.parquet")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--skip", type=int, default=0, help="start after this many rows")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--rate", type=float, default=5.0, help="transactions per second")
    args = parser.parse_args()

    df = pd.read_parquet(args.inp).drop(columns=LABEL_COLUMNS).iloc[args.skip:args.skip + args.limit]
    df["event_time"] = df["event_time"].map(lambda t: t.isoformat())  # Timestamp -> "2026-09-01T...+00:00"

    codes: Counter = Counter()
    with httpx.Client(base_url=args.url, timeout=10) as client:  # one connection reused for all requests
        for row in df.to_dict(orient="records"):
            row["amount_minor"] = int(row["amount_minor"])  # numpy int -> JSON int
            response = client.post("/transactions", json=row)
            codes[response.status_code] += 1
            time.sleep(1 / args.rate)

    print("HTTP status counts:", dict(codes))  # expect {202: N} first time, {200: N} if replayed again


if __name__ == "__main__":
    main()