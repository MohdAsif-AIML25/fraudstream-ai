"""Build the offline feature table from raw transactions.

Run from project root:  python -m scripts.build_features
"""

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

from app.features.offline import build_feature_table


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inp", type=Path, default=Path("data/raw/transactions.parquet"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/features.parquet"))
    args = parser.parse_args()

    raw = pd.read_parquet(args.inp)
    started = time.perf_counter()
    features = build_feature_table(raw)
    elapsed = time.perf_counter() - started

    assert len(features) == len(raw), "feature table must have exactly one row per transaction"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(args.out, index=False)
    print(f"[OK] {len(features):,} rows in {elapsed:.1f}s -> {args.out}")
    print(features.drop(columns=["transaction_id", "account_id"]).describe().T.round(2))
    return 0


if __name__ == "__main__":
    sys.exit(main())