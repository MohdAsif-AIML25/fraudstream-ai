"""Baselines and the model pipelines.

Every model exposes predict_proba(X) so evaluation code treats them all the same.
"""

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.models.columns import CATEGORICAL_FEATURES, NUMERIC_FEATURES


class MajorityBaseline:
    """Always predicts 'legit'. Exists to show why accuracy is a misleading metric."""

    def fit(self, X, y):
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return np.column_stack([np.ones(len(X)), np.zeros(len(X))])  # [P(legit), P(fraud)]


class RuleBaseline:
    """What a fraud analyst might hand-write. Score = how many red flags fire (0..1)."""

    def fit(self, X, y):
        return self

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        burst = X["prior_txn_count_5m"] >= 3                                       # velocity
        takeover = (X["is_new_device"] == 1) & (X["amount_to_prior_average"] > 5)  # new device + big spend
        score = (burst.astype(float) + takeover.astype(float)) / 2
        return np.column_stack([1 - score, score])


def _preprocessor(scale_numeric: bool) -> ColumnTransformer:
    numeric = StandardScaler() if scale_numeric else "passthrough"  # trees don't need scaling
    return ColumnTransformer([
        ("num", numeric, NUMERIC_FEATURES),
        # handle_unknown="ignore": a category unseen in training becomes all-zeros, not a crash
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
    ])


def build_logreg() -> Pipeline:
    """Preprocessing INSIDE the pipeline -> the saved artifact scales/encodes exactly like training."""
    return Pipeline([
        ("prep", _preprocessor(scale_numeric=True)),
        # class_weight="balanced": a missed fraud costs ~200x a missed legit row (inverse class frequency)
        ("model", LogisticRegression(class_weight="balanced", max_iter=2000)),
    ])


def build_preprocessor_for_trees() -> ColumnTransformer:
    return _preprocessor(scale_numeric=False)