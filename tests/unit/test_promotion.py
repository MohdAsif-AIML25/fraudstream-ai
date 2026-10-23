"""Champion vs. challenger gate: promote only a candidate that is no worse AND better somewhere."""

from dataclasses import replace

import pandas as pd
import pytest

from app.models.columns import MODEL_COLUMNS
from app.models.promotion import ModelReport, PromotionGate, build_report, compare

DEPLOYED = ModelReport(
    model_version="fraud_model_v1", feature_columns=MODEL_COLUMNS, threshold=0.18,
    pr_auc=0.95, recall_at_fpr=0.98, precision=0.21, recall=1.0, flagged_rate=0.024,
    total_cost_minor=1_770_000, fraud_caught_minor=48_000_000, latency_p95_ms=7.0,
)


def failed(decision) -> list[str]:
    return [c.name for c in decision.checks if not c.passed]


def test_cheaper_and_no_worse_candidate_is_promoted():
    candidate = replace(DEPLOYED, model_version="v2", total_cost_minor=1_500_000)
    decision = compare(DEPLOYED, candidate)
    assert decision.promote and failed(decision) == []


def test_identical_candidate_is_not_promoted():
    # Passing every guardrail is not enough: a new model must be BETTER at something.
    decision = compare(DEPLOYED, replace(DEPLOYED, model_version="v2"))
    assert not decision.promote and failed(decision) == ["better on cost or PR-AUC"]


def test_recall_regression_blocks_promotion_even_if_cheaper():
    candidate = replace(DEPLOYED, model_version="v2", total_cost_minor=1_000_000, recall_at_fpr=0.95)
    decision = compare(DEPLOYED, candidate)
    assert not decision.promote and failed(decision) == ["recall @ 1% FPR not worse"]


@pytest.mark.parametrize("change, check", [
    ({"pr_auc": 0.90}, "PR-AUC not worse"),
    ({"flagged_rate": 0.05}, "analyst workload"),
    ({"latency_p95_ms": 120.0}, "latency"),
    ({"feature_columns": MODEL_COLUMNS[:-1]}, "feature contract"),
])
def test_each_guardrail_can_block(change, check):
    candidate = replace(DEPLOYED, model_version="v2", total_cost_minor=1_000_000, **change)
    decision = compare(DEPLOYED, candidate)
    assert not decision.promote and check in failed(decision)


def test_small_noise_within_tolerance_is_accepted():
    gate = PromotionGate()
    candidate = replace(DEPLOYED, model_version="v2", total_cost_minor=1_600_000,
                        pr_auc=DEPLOYED.pr_auc - gate.max_pr_auc_drop / 2)
    assert compare(DEPLOYED, candidate, gate).promote


def test_build_report_from_scores():
    X = pd.DataFrame({"amount_minor": [1000, 200, 3000, 50, 10]})
    report = build_report("m", [0.9, 0.8, 0.3, 0.2, 0.1], X, [1, 0, 1, 0, 0], threshold=0.5,
                          latency_p95_ms=3.0, feature_columns=MODEL_COLUMNS)
    assert report.recall == 0.5 and report.flagged_rate == pytest.approx(0.4)
    assert report.fraud_caught_minor == 1000
    assert report.pr_auc == pytest.approx((1 + 2 / 3) / 2)
