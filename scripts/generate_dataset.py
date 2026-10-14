"""Generate the synthetic dataset and validate it against the data contract.

Run from project root:  python -m scripts.generate_dataset
"""

import argparse
import sys
from pathlib import Path

from app.data.synthetic import GeneratorConfig, generate_transactions
from app.data.validation import validate_against_contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounts", type=int, default=2000)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data/raw/transactions.parquet"))
    args = parser.parse_args()

    cfg = GeneratorConfig(n_accounts=args.accounts, n_days=args.days, seed=args.seed)
    df = generate_transactions(cfg)

    errors = validate_against_contract(df)
    if errors:  # fail fast: never save data the API would reject
        print(f"[FAIL] {len(errors)} contract violations, first 5:")
        for e in errors[:5]:
            print("   ", e)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Parquet keeps types (timezone-aware timestamps, ints) unlike CSV, and is much smaller.
    df.to_parquet(args.out, index=False)
    print(f"[OK] {len(df):,} transactions, fraud rate {df['is_fraud'].mean():.2%} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())