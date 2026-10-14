"""Smoke test: train a small model, save it with metadata, reload it, score one transaction.
This is exactly what the Day 5 worker does at startup and per event."""

import json

from app.data.synthetic import GeneratorConfig, generate_transactions
from app.features.offline import build_feature_table
from app.models.artifact import load_model, risk_band, save_model
from app.models.baselines import build_logreg
from app.models.columns import MODEL_COLUMNS, split_xy


def test_saved_model_reloads_and_scores_one_row(tmp_path):  # tmp_path: pytest gives a temp folder
    df = build_feature_table(generate_transactions(GeneratorConfig(n_accounts=300, n_days=7, seed=3)))
    X, y = split_xy(df)
    model = build_logreg().fit(X, y)

    thresholds = {"high": 0.8, "medium": 0.5}
    path = save_model(model, "test_model", thresholds, metrics={}, extra={},
                      artifact_dir=tmp_path, meta_dir=tmp_path)

    reloaded = load_model(path)
    score = float(reloaded.predict_proba(X.iloc[[0]])[:, 1][0])
    assert 0.0 <= score <= 1.0
    assert risk_band(score, thresholds) in {"low", "medium", "high"}

    meta = json.loads((tmp_path / "test_model.json").read_text())
    assert meta["feature_columns"] == MODEL_COLUMNS   # the worker relies on this list


def test_risk_band_boundaries():
    t = {"high": 0.8, "medium": 0.5}
    assert risk_band(0.8, t) == "high"     # boundary belongs to the higher band
    assert risk_band(0.5, t) == "medium"
    assert risk_band(0.49, t) == "low"