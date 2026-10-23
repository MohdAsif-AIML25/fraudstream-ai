"""Metrics checked against a tiny example computed by hand.

labels: [1, 0, 1, 0, 0]
scores: [0.9, 0.8, 0.3, 0.2, 0.1]   threshold 0.5 -> predictions [1, 1, 0, 0, 0]
TP=1 (row 0)  FP=1 (row 1)  FN=1 (row 2)  TN=2
precision = 1/2, recall = 1/2
"""

import pytest

from app.models.evaluate import CostModel, evaluate, fraud_cost, recall_at_fpr, threshold_for_budget

Y = [1, 0, 1, 0, 0]
S = [0.9, 0.8, 0.3, 0.2, 0.1]


def test_confusion_counts_and_rates():
    m = evaluate(Y, S, threshold=0.5)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 2)
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)
    assert m["flagged_rate"] == pytest.approx(0.4)


def test_average_precision_by_hand():
    # Ranked: 0.9(fraud) P=1/1 ; 0.8(legit) ; 0.3(fraud) P=2/3 -> AP = (1 + 2/3) / 2
    assert evaluate(Y, S, 0.5)["average_precision"] == pytest.approx((1 + 2 / 3) / 2)


def test_majority_model_has_zero_recall_despite_high_accuracy():
    y = [0] * 99 + [1]
    m = evaluate(y, [0.0] * 100, threshold=0.5)
    assert m["recall"] == 0          # catches no fraud...
    assert m["tn"] == 99             # ...while being "99% accurate"


def test_budget_threshold_flags_about_that_share():
    scores = [i / 100 for i in range(100)]
    t = threshold_for_budget(scores, budget=0.10)
    flagged = sum(s >= t for s in scores)
    assert 9 <= flagged <= 11


def test_recall_at_fpr_by_hand():
    # No legit flagged allowed -> only the 0.9 fraud is above every legit score: recall 1/2.
    assert recall_at_fpr(Y, S, max_fpr=0.0) == {"recall": 0.5, "fpr": 0.0, "threshold": 0.9}
    # 1 of 3 legit allowed (0.8) -> threshold drops to 0.3 and both frauds are caught.
    r = recall_at_fpr(Y, S, max_fpr=0.34)
    assert r["recall"] == 1.0 and r["fpr"] == pytest.approx(1 / 3) and r["threshold"] == 0.3


def test_recall_at_fpr_without_fraud_is_zero():
    assert recall_at_fpr([0, 0, 0], [0.1, 0.2, 0.3])["recall"] == 0.0


def test_fraud_cost_by_hand():
    # threshold 0.5 flags rows 0 and 1. Row 2 is fraud and missed: its amount + chargeback fee is lost.
    cost = fraud_cost(Y, S, amounts_minor=[1000, 200, 3000, 50, 10], threshold=0.5,
                      costs=CostModel(review_cost_minor=100, chargeback_fee_minor=500))
    assert cost == {"missed_fraud_cost_minor": 3000 + 500, "review_cost_minor": 2 * 100,
                    "total_cost_minor": 3700, "fraud_caught_minor": 1000}
