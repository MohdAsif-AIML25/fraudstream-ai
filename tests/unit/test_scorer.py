"""Scorer tests with a tiny stub model, so they run in milliseconds and test OUR code,
not XGBoost."""

import numpy as np
import pytest

from app.models.columns import MODEL_COLUMNS
from app.models.scorer import ModelContractError, Scorer
from app.schemas import Transaction

THRESHOLDS = {"high": 0.8, "medium": 0.3}


class StubModel:
    """Returns a fixed probability and remembers the DataFrame it received."""

    def __init__(self, probability: float) -> None:
        self.probability = probability
        self.seen = None

    def predict_proba(self, X):
        self.seen = X
        return np.array([[1 - self.probability, self.probability]])


def metadata(columns=MODEL_COLUMNS) -> dict:
    return {"feature_columns": list(columns), "thresholds": THRESHOLDS, "model_version": "fraud_model_v1"}


def txn() -> Transaction:
    return Transaction(transaction_id="txn_1", account_id="acct_1", device_id="dev_1",
                       event_time="2026-10-11T14:20:00Z", amount_minor=2_500_000, currency="INR",
                       merchant_category="electronics", channel="online")


FEATURES = {"prior_txn_count_5m": 2.0, "prior_amount_sum_5m": 80_000.0, "seconds_since_previous_txn": 150.0,
            "is_new_device": 1.0, "amount_to_prior_average": 62.5, "history_available": 1.0,
            "hour_of_day_ist": 19.0}


def test_refuses_to_start_when_model_and_code_disagree():
    with pytest.raises(ModelContractError):
        Scorer(StubModel(0.1), metadata(columns=MODEL_COLUMNS[:-1]))  # one column missing


def test_builds_one_row_in_training_column_order():
    model = StubModel(0.5)
    Scorer(model, metadata()).score(txn(), FEATURES)
    assert list(model.seen.columns) == MODEL_COLUMNS
    assert model.seen.loc[0, "merchant_category"] == "electronics"  # plain string, like training data
    assert model.seen.loc[0, "amount_minor"] == 2_500_000


@pytest.mark.parametrize("probability, band", [(0.95, "high"), (0.8, "high"), (0.5, "medium"), (0.1, "low")])
def test_band_follows_validation_thresholds(probability, band):
    result = Scorer(StubModel(probability), metadata()).score(txn(), FEATURES)
    assert result.band == band
    assert result.model_version == "fraud_model_v1"