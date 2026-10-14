"""Chronological train / validation / test split.

Why not a random split?
  1. Time: in production we always predict the FUTURE from the PAST. A random split lets
     the model train on October and be tested on September, which is unrealistic.
  2. Leakage: rows from the same fraud burst would land in both train and test,
     so the model "recognises" the incident instead of generalising.
"""

import pandas as pd


def chronological_split(
    df: pd.DataFrame,
    time_col: str = "event_time",
    train_frac: float = 0.70,
    val_frac: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Earliest rows -> train, middle -> validation, latest -> test.

    Boundaries are TIMES, not row counts, so events with the same timestamp
    always land in the same split.
    """
    # Brackets matter: without them "not" would apply only to the first comparison.
    if not (0 < train_frac and 0 < val_frac and train_frac + val_frac < 1):
        raise ValueError("fractions must be positive and leave room for a test set")

    times = df[time_col]
    train_end = times.quantile(train_frac)           # e.g. the 70th-percentile timestamp
    val_end = times.quantile(train_frac + val_frac)  # e.g. the 85th-percentile timestamp

    train = df[times < train_end]
    val = df[(times >= train_end) & (times < val_end)]
    test = df[times >= val_end]
    return train, val, test