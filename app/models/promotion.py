"""Champion vs. challenger: should a candidate model replace the deployed one?

Both models are scored on the SAME held-out transactions, each at its own "high" threshold
(chosen on validation with the same review budget). The candidate is promoted only if it
passes every guardrail AND is better on at least one thing the business cares about.

Guardrails (never get worse beyond a tolerance):
    PR-AUC, recall at a fixed false-positive rate, analyst workload, p95 latency, feature contract
Improvement (at least one):
    lower estimated fraud cost, or higher PR-AUC

No HTTP, no files, no MLflow here: scripts/compare_models.py does the I/O, this module decides.
"""

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from app.models.columns import MODEL_COLUMNS
from app.models.evaluate import CostModel, evaluate, fraud_cost, recall_at_fpr


@dataclass(frozen=True)
class PromotionGate:
    max_pr_auc_drop: float = 0.005       # tolerate noise, not a real regression
    max_recall_drop: float = 0.01        # recall at the fixed FPR
    min_pr_auc_gain: float = 0.005      # counts as an improvement
    max_flagged_rate: float = 0.03       # analysts can review ~2%; 3% is the hard ceiling
    max_latency_p95_ms: float = 50.0     # one transaction, model only
    max_fpr: float = 0.01                # recall is compared at 1% false positives


@dataclass
class ModelReport:
    model_version: str
    feature_columns: list[str]
    threshold: float
    pr_auc: float
    recall_at_fpr: float
    precision: float
    recall: float
    flagged_rate: float
    total_cost_minor: int
    fraud_caught_minor: int
    latency_p95_ms: float


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class PromotionDecision:
    promote: bool
    checks: list[Check] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"promote": self.promote, "checks": [asdict(c) for c in self.checks]}


def build_report(model_version: str, scores, X: pd.DataFrame, y, threshold: float, latency_p95_ms: float,
                 feature_columns: list[str], gate: PromotionGate = PromotionGate(),
                 costs: CostModel = CostModel()) -> ModelReport:
    """All metrics for one model on one evaluation set."""
    scores = np.asarray(scores, dtype=float)
    at_threshold = evaluate(y, scores, threshold)
    cost = fraud_cost(y, scores, X["amount_minor"], threshold, costs)
    return ModelReport(
        model_version=model_version,
        feature_columns=list(feature_columns),
        threshold=float(threshold),
        pr_auc=at_threshold["average_precision"],
        recall_at_fpr=recall_at_fpr(y, scores, gate.max_fpr)["recall"],
        precision=at_threshold["precision"],
        recall=at_threshold["recall"],
        flagged_rate=at_threshold["flagged_rate"],
        total_cost_minor=cost["total_cost_minor"],
        fraud_caught_minor=cost["fraud_caught_minor"],
        latency_p95_ms=float(latency_p95_ms),
    )


def compare(deployed: ModelReport, candidate: ModelReport, gate: PromotionGate = PromotionGate()) -> PromotionDecision:
    d, c = deployed, candidate
    guardrails = [
        Check("feature contract", c.feature_columns == MODEL_COLUMNS,
              "candidate uses the columns the worker builds" if c.feature_columns == MODEL_COLUMNS
              else f"candidate expects {c.feature_columns}"),
        Check("PR-AUC not worse", c.pr_auc >= d.pr_auc - gate.max_pr_auc_drop,
              f"{c.pr_auc:.4f} vs {d.pr_auc:.4f} (tolerance {gate.max_pr_auc_drop})"),
        Check(f"recall @ {gate.max_fpr:.0%} FPR not worse", c.recall_at_fpr >= d.recall_at_fpr - gate.max_recall_drop,
              f"{c.recall_at_fpr:.3f} vs {d.recall_at_fpr:.3f} (tolerance {gate.max_recall_drop})"),
        Check("analyst workload", c.flagged_rate <= gate.max_flagged_rate,
              f"flags {c.flagged_rate:.2%} of traffic (limit {gate.max_flagged_rate:.0%})"),
        Check("latency", c.latency_p95_ms <= gate.max_latency_p95_ms,
              f"p95 {c.latency_p95_ms:.1f} ms (limit {gate.max_latency_p95_ms:.0f} ms)"),
    ]
    cheaper = c.total_cost_minor < d.total_cost_minor
    sharper = c.pr_auc >= d.pr_auc + gate.min_pr_auc_gain
    improvement = Check(
        "better on cost or PR-AUC", cheaper or sharper,
        f"cost ₹{c.total_cost_minor / 100:,.0f} vs ₹{d.total_cost_minor / 100:,.0f}; "
        f"PR-AUC gain {c.pr_auc - d.pr_auc:+.4f} (needs +{gate.min_pr_auc_gain})",
    )
    checks = guardrails + [improvement]
    return PromotionDecision(promote=all(ch.passed for ch in checks), checks=checks)
