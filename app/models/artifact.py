"""Save/load the deployable model together with its metadata.

The .joblib binary is gitignored; the small .json metadata IS committed, so the repo
always records which features, thresholds and metrics version 1 shipped with.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib

from app.models.columns import MODEL_COLUMNS

META_DIR = Path("artifacts_meta")


def save_model(model, name: str, thresholds: dict, metrics: dict, extra: dict, artifact_dir: Path,
               meta_dir: Path = META_DIR) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / f"{name}.joblib"
    joblib.dump(model, model_path)

    metadata = {
        "model_version": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "feature_columns": MODEL_COLUMNS,  # the worker must build exactly these columns
        "thresholds": thresholds,          # score -> band mapping
        "metrics": metrics,
        **extra,
    }
    (meta_dir / f"{name}.json").write_text(json.dumps(metadata, indent=2))
    return model_path


def load_model(path: Path):
    return joblib.load(path)


def risk_band(score: float, thresholds: dict) -> str:
    """Map a score to a band. Bands, not raw scores, drive the review decision."""
    if score >= thresholds["high"]:
        return "high"      # -> review queue
    if score >= thresholds["medium"]:
        return "medium"    # -> monitor
    return "low"           # -> allow