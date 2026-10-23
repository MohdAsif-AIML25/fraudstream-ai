"""Evaluation metrics for imbalanced fraud detection.

Accuracy is deliberately NOT here: with 0.5% fraud, "always legit" scores 99.5%
accuracy and catches nothing.
"""

from dataclasses import dataclass

import numpy as np
from sklearn.metrics import average_precision_score, confusion_matrix, precision_score, recall_score, roc_curve


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


def recall_at_fpr(y_true, scores, max_fpr: float = 0.01) -> dict[str, float]:
    """Best recall reachable while at most `max_fpr` of LEGIT transactions are flagged.

    Fixing the false-positive rate makes two models comparable on equal terms: "with the same
    customer friction, which one catches more fraud?" (comparing at each model's own threshold doesn't).
    """
    y_true = np.asarray(y_true)
    if not y_true.any() or y_true.all():
        return {"recall": 0.0, "fpr": 0.0, "threshold": 1.0}
    fpr, tpr, thresholds = roc_curve(y_true, np.asarray(scores, dtype=float))
    best = np.flatnonzero(fpr <= max_fpr)[-1]  # fpr rises along the curve -> last point within budget
    return {"recall": float(tpr[best]), "fpr": float(fpr[best]), "threshold": float(min(thresholds[best], 1.0))}


@dataclass(frozen=True)
class CostModel:
    """Money view of the confusion matrix, in paise (like amount_minor).

    missed fraud    -> we lose the transaction amount + a chargeback fee
    every flagged   -> an analyst spends time reviewing it
    These are ASSUMPTIONS; change them to the business's real numbers.
    """

    review_cost_minor: int = 5_000       # ₹50 of analyst time per reviewed transaction
    chargeback_fee_minor: int = 50_000   # ₹500 handling fee per missed fraud


def fraud_cost(y_true, scores, amounts_minor, threshold: float, costs: CostModel = CostModel()) -> dict[str, int]:
    """Estimated cost at a threshold. Lower is better; compare models on the SAME transactions."""
    y_true = np.asarray(y_true).astype(bool)
    flagged = np.asarray(scores, dtype=float) >= threshold
    amounts = np.asarray(amounts_minor, dtype=np.int64)

    missed = y_true & ~flagged
    missed_fraud = int(amounts[missed].sum()) + int(missed.sum()) * costs.chargeback_fee_minor
    review = int(flagged.sum()) * costs.review_cost_minor
    return {
        "missed_fraud_cost_minor": missed_fraud,
        "review_cost_minor": review,
        "total_cost_minor": missed_fraud + review,
        "fraud_caught_minor": int(amounts[y_true & flagged].sum()),  # money the review queue protects
    }