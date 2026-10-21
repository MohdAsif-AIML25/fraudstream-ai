"""Load the Day 3 model ONCE and score one transaction at a time.

The metadata JSON written by select_model.py is the model's "contract": which columns, in which
order, and which thresholds. The scorer refuses to start if the code and the model disagree,
because a silent column mismatch produces confident nonsense instead of an error.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from app.models.artifact import load_model, risk_band
from app.models.columns import MODEL_COLUMNS
from app.schemas import Transaction


class ModelContractError(Exception):
    """The model artifact expects different features than this code produces."""


@dataclass(frozen=True)
class ScoreResult:
    score: float          # probability of fraud, 0..1
    band: str             # low / medium / high
    model_version: str


class Scorer:
    def __init__(self, model, metadata: dict) -> None:
        if metadata["feature_columns"] != MODEL_COLUMNS:
            # Fail at STARTUP, not on the 10,000th transaction.
            raise ModelContractError(
                f"model expects {metadata['feature_columns']}, code builds {MODEL_COLUMNS}"
            )
        self._model = model
        self.thresholds: dict = metadata["thresholds"]
        self.model_version: str = metadata["model_version"]

    @classmethod
    def from_files(cls, model_path: str | Path, meta_path: str | Path) -> "Scorer":
        metadata = json.loads(Path(meta_path).read_text())
        return cls(load_model(Path(model_path)), metadata)

    def score(self, txn: Transaction, features: dict[str, float]) -> ScoreResult:
        # Build ONE row with exactly the training columns, in the training order.
        row = {
            **features,
            "amount_minor": txn.amount_minor,
            "merchant_category": txn.merchant_category.value,  # Enum -> "electronics", as in training
            "channel": txn.channel.value,
        }
        X = pd.DataFrame([row], columns=MODEL_COLUMNS)  # columns= fixes the order
        probability = float(self._model.predict_proba(X)[0, 1])  # [row 0, class 1 = fraud]
        return ScoreResult(probability, risk_band(probability, self.thresholds), self.model_version)