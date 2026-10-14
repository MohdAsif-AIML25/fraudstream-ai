"""Shared helpers for training scripts: load + split data, MLflow setup, latency measurement."""

import time
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd

from app.models.split import chronological_split

FEATURES_PATH = Path("data/processed/features.parquet")
ARTIFACT_DIR = Path("artifacts")  # gitignored: model binaries go to MLflow/S3, not Git


def load_splits(path: Path = FEATURES_PATH):
    df = pd.read_parquet(path)
    return chronological_split(df)


def start_tracking(experiment: str) -> None:
    # Explicit SQLite backend: works the same regardless of MLflow version defaults.
    mlflow.set_tracking_uri("sqlite:///mlflow.db")
    mlflow.set_experiment(experiment)


def dataset_tags(train, val, test) -> dict:
    """Record WHICH data a run used, so results are reproducible and comparable."""
    return {
        "train_rows": len(train), "val_rows": len(val), "test_rows": len(test),
        "train_end": str(train["event_time"].max()), "val_end": str(val["event_time"].max()),
        "train_fraud_rate": round(float(train["is_fraud"].mean()), 5),
    }


def single_row_latency_ms(model, X: pd.DataFrame, n: int = 200) -> dict[str, float]:
    """Time predict_proba on ONE row at a time, the way the worker will score events."""
    timings = []
    for i in range(min(n, len(X))):
        row = X.iloc[[i]]  # double brackets -> 1-row DataFrame, not a Series
        start = time.perf_counter()
        model.predict_proba(row)
        timings.append((time.perf_counter() - start) * 1000)
    return {"latency_p50_ms": float(np.percentile(timings, 50)),
            "latency_p95_ms": float(np.percentile(timings, 95))}