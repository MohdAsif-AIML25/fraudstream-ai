"""Champion vs. challenger: compare a candidate model with the DEPLOYED one before promotion.

Run from project root:
    python -m scripts.train_xgboost --name xgboost_v2 --max-depth 6       # train a challenger
    python -m scripts.compare_models --candidate artifacts/xgboost_v2.joblib
    python -m scripts.compare_models --candidate artifacts/xgboost_v2.joblib --promote --name fraud_model_v2

Both models score the same held-out (test) transactions. The candidate gets its thresholds from
VALIDATION with the same review budget the deployed model used, so neither sees the test labels
before being judged. The rules are in app/models/promotion.py.

Output: a side-by-side table, an MLflow run (experiment "fraudstream-promotion") and a JSON report
in artifacts_meta/comparisons/. Exit code 0 = candidate passes the gate, 2 = it does not.

--promote writes the candidate as a new versioned model (artifacts/<name>.joblib + artifacts_meta/<name>.json).
It does NOT touch the running worker: point MODEL_PATH / MODEL_META_PATH at the new files and restart it.
Rolling back = pointing them at the old files again.
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import joblib
import mlflow

from app.config import get_settings
from app.models.artifact import META_DIR, save_model
from app.models.columns import MODEL_COLUMNS, split_xy
from app.models.evaluate import CostModel, evaluate, threshold_for_budget
from app.models.promotion import PromotionGate, build_report, compare
from app.models.tracking import ARTIFACT_DIR, load_splits, single_row_latency_ms, start_tracking
from scripts.select_model import HIGH_BUDGET, MEDIUM_BUDGET

ROWS = [  # (label, attribute, format)
    ("PR-AUC (average precision)", "pr_auc", "{:.4f}"),
    ("recall @ 1% FPR", "recall_at_fpr", "{:.3f}"),
    ("threshold (high band)", "threshold", "{:.4f}"),
    ("precision @ high", "precision", "{:.3f}"),
    ("recall @ high", "recall", "{:.3f}"),
    ("traffic flagged", "flagged_rate", "{:.2%}"),
    ("estimated cost (₹)", "total_cost_minor", "money"),
    ("fraud caught (₹)", "fraud_caught_minor", "money"),
    ("p95 latency, 1 row (ms)", "latency_p95_ms", "{:.1f}"),
]


def _fmt(value, fmt: str) -> str:
    return f"{value / 100:,.0f}" if fmt == "money" else fmt.format(value)


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", type=Path, required=True, help="candidate .joblib pipeline")
    parser.add_argument("--deployed-model", type=Path, default=Path(settings.model_path))
    parser.add_argument("--deployed-meta", type=Path, default=Path(settings.model_meta_path))
    parser.add_argument("--promote", action="store_true", help="save the candidate as a new model version if it passes")
    parser.add_argument("--name", default=None, help="version name for --promote, e.g. fraud_model_v2")
    parser.add_argument("--review-cost", type=int, default=CostModel.review_cost_minor, help="paise per reviewed txn")
    parser.add_argument("--chargeback-fee", type=int, default=CostModel.chargeback_fee_minor, help="paise per missed fraud")
    args = parser.parse_args()
    if args.promote and not args.name:
        parser.error("--promote needs --name (the new model version)")

    costs = CostModel(review_cost_minor=args.review_cost, chargeback_fee_minor=args.chargeback_fee)
    gate = PromotionGate()

    _, val, test = load_splits()
    X_val, y_val = split_xy(val)
    X_test, y_test = split_xy(test)

    deployed_meta = json.loads(args.deployed_meta.read_text())
    deployed = joblib.load(args.deployed_model)
    candidate = joblib.load(args.candidate)
    candidate_version = args.name or args.candidate.stem

    # Candidate thresholds: same budgets as select_model.py, chosen on VALIDATION only.
    val_scores = candidate.predict_proba(X_val)[:, 1]
    candidate_thresholds = {"high": threshold_for_budget(val_scores, HIGH_BUDGET),
                            "medium": threshold_for_budget(val_scores, MEDIUM_BUDGET)}

    d_scores = deployed.predict_proba(X_test)[:, 1]
    c_scores = candidate.predict_proba(X_test)[:, 1]
    d = build_report(deployed_meta["model_version"], d_scores, X_test, y_test, deployed_meta["thresholds"]["high"],
                     single_row_latency_ms(deployed, X_test)["latency_p95_ms"],
                     deployed_meta["feature_columns"], gate, costs)
    c = build_report(candidate_version, c_scores, X_test, y_test, candidate_thresholds["high"],
                     single_row_latency_ms(candidate, X_test)["latency_p95_ms"],
                     list(candidate.feature_names_in_) if hasattr(candidate, "feature_names_in_") else MODEL_COLUMNS,
                     gate, costs)
    decision = compare(d, c, gate)

    # ---------- report ----------
    print(f"\nEvaluated on {len(y_test):,} test transactions ({int(y_test.sum())} fraud)\n")
    print(f"{'':28}{'deployed: ' + d.model_version:>28}{'candidate: ' + c.model_version:>28}")
    for label, attr, fmt in ROWS:
        print(f"{label:28}{_fmt(getattr(d, attr), fmt):>28}{_fmt(getattr(c, attr), fmt):>28}")
    print()
    for check in decision.checks:
        print(f"  [{'PASS' if check.passed else 'FAIL'}] {check.name}: {check.detail}")
    print(f"\nDECISION: {'PROMOTE' if decision.promote else 'KEEP the deployed model'}")

    report = {"deployed": asdict(d), "candidate": asdict(c), "gate": asdict(gate), "costs": asdict(costs),
              "test_rows": len(y_test), "test_fraud": int(y_test.sum()), **decision.to_dict()}
    out = META_DIR / "comparisons" / f"{c.model_version}_vs_{d.model_version}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"report: {out}")

    start_tracking("fraudstream-promotion")
    with mlflow.start_run(run_name=f"{c.model_version} vs {d.model_version}"):
        numeric = [attr for _, attr, _ in ROWS]
        mlflow.log_metrics({f"deployed_{a}": float(getattr(d, a)) for a in numeric}
                           | {f"candidate_{a}": float(getattr(c, a)) for a in numeric})
        mlflow.set_tags({"deployed": d.model_version, "candidate": c.model_version, "promote": decision.promote})
        mlflow.log_dict(report, "comparison.json")

    if args.promote:
        if not decision.promote:
            print("\n--promote refused: the candidate did not pass the gate.")
            return 2
        save_model(
            candidate, name=args.name, thresholds=candidate_thresholds,
            metrics={"validation": evaluate(y_val, val_scores, candidate_thresholds["high"]),
                     "test": evaluate(y_test, c_scores, candidate_thresholds["high"])},
            extra={"algorithm": type(candidate[-1]).__name__ if hasattr(candidate, "steps") else type(candidate).__name__,
                   "promoted_over": d.model_version, "comparison_report": str(out)},
            artifact_dir=ARTIFACT_DIR,
        )
        print(f"\nPromoted -> {ARTIFACT_DIR / (args.name + '.joblib')}. To serve it, set in .env and restart the worker:")
        print(f"  MODEL_PATH=artifacts/{args.name}.joblib")
        print(f"  MODEL_META_PATH=artifacts_meta/{args.name}.json")
        print("  docker compose up -d --build worker   # --build: the metadata JSON is baked into the image")

    return 0 if decision.promote else 2


if __name__ == "__main__":
    sys.exit(main())
