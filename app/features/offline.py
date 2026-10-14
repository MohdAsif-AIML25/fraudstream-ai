"""Offline feature builder: raw transactions table -> feature table for training.

It replays every account's events in time order through AccountHistory,
exactly the way the live worker will receive them one by one.
"""

import pandas as pd

from app.features.compute import FEATURE_NAMES, AccountHistory, Event

# Columns copied through unchanged (IDs for joins, raw categoricals the model also uses, labels).
PASSTHROUGH = ["transaction_id", "account_id", "event_time", "amount_minor", "merchant_category", "channel"]
LABEL_COLUMNS = ["is_fraud", "fraud_scenario"]


def build_feature_table(transactions: pd.DataFrame) -> pd.DataFrame:
    """Return one row per transaction: passthrough columns + FEATURE_NAMES (+ labels if present)."""
    # Sort by account, then time; transaction_id breaks exact-time ties so output is deterministic.
    ordered = transactions.sort_values(["account_id", "event_time", "transaction_id"], kind="mergesort")

    histories: dict[str, AccountHistory] = {}  # one rolling state per account
    rows = []
    # itertuples is much faster than iterrows (no Series object per row)
    for row in ordered.itertuples(index=False):
        event = Event(
            event_time=row.event_time.to_pydatetime(),  # pandas Timestamp -> python datetime (tz kept)
            amount_minor=int(row.amount_minor),
            device_id=row.device_id,
        )
        history = histories.setdefault(row.account_id, AccountHistory())
        features = history.features_for(event)  # 1) read state BEFORE this event
        history.add(event)                      # 2) then update state with it
        rows.append(features)

    features_df = pd.DataFrame(rows, columns=list(FEATURE_NAMES), index=ordered.index)

    keep = PASSTHROUGH + [c for c in LABEL_COLUMNS if c in ordered.columns]
    result = pd.concat([ordered[keep], features_df], axis=1)
    # Return in global time order: the Day 3 chronological split expects this.
    return result.sort_values(["event_time", "transaction_id"], kind="mergesort").reset_index(drop=True)