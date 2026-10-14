"""Which columns the model uses. One list, imported everywhere (training, scoring, tests)."""

import pandas as pd

from app.features.compute import FEATURE_NAMES 

NUMERIC_FEATURES = list(FEATURE_NAMES) + ["amount_minor"]  # behaviour features + raw amount
CATEGORICAL_FEATURES = ["merchant_category", "channel"]
MODEL_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
LABEL = "is_fraud"

def split_xy(df:pd.DataFrame)-> tuple[pd.DataFrame,pd.Series]:
    """Select model inputs (X) and the label (y). IDs, time and fraud_scenario are left out:
    they are not available at prediction time or would let the model cheat."""
    return df[MODEL_COLUMNS], df[LABEL].astype(int)