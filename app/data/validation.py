"""Check generated data against the Day 1 data contract.

Labels (is_fraud, fraud_scenario) are NOT part of the contract: a real client
never sends "is_fraud". We strip them before validating.
"""

import pandas as pd
from pydantic import ValidationError

from app.schemas import Transaction

LABEL_COLUMNS = {"is_fraud", "fraud_scenario"}


def validate_against_contract(df: pd.DataFrame) -> list[str]:
    """Return a list of error messages (empty list = every row is valid)."""
    errors = []
    contract_cols = [c for c in df.columns if c not in LABEL_COLUMNS]
    for row in df[contract_cols].to_dict(orient="records"):
        row["event_time"] = row["event_time"].to_pydatetime()  # pandas Timestamp -> datetime
        row["amount_minor"] = int(row["amount_minor"])         # numpy int64 -> int (strict=True needs real int)
        try:
            Transaction(**row)
        except ValidationError as exc:
            errors.append(f"{row['transaction_id']}: {exc.errors()[0]['msg']}")

    duplicates = df["transaction_id"].duplicated().sum()
    if duplicates:
        errors.append(f"{duplicates} duplicate transaction_id values")
    return errors