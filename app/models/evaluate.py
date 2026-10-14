"""Evaluation metrics for imbalanced fraud detection.

Accuracy is deliberately NOT here: with 0.5% fraud, "always legit" scores 99.5%
accuracy and catches nothing.
"""

import numpy as np
from sklearn.metrics import average_precision_score, confusion_matrix, precision_score, recall_score


def threshold_for_budget(scores: np.ndarray, budget: float) -> float:
    """Score threshold that flags roughly the top `budget` fraction of transactions.
    budget=0.02 -> analysts review the riskiest 2%."""
    return float(np.quantile(scores, 1 - budget))


def evaluate(y_true, scores, threshold: float) -> dict[str, float]:
    """Threshold-free and threshold-based metrics in one dictionary (easy to log to MLflow)."""
    y_true = np.asarray(y_true)
    scores = np.asarray(scores, dtype=float)
    y_pred = (scores >= threshold).astype(int)

    # labels=[0, 1] forces a 2x2 matrix even if one class is missing
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return {
        # Average precision = area under precision-recall curve. Random model ~= fraud rate.
        "average_precision": float(average_precision_score(y_true, scores)) if y_true.any() else 0.0,
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),  # of flagged, how many fraud
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),        # of fraud, how many flagged
        "flagged_rate": float(y_pred.mean()),  # share of traffic sent to review (analyst workload)
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
    }