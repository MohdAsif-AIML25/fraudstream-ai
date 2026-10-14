"""Stage 6b: pick the model, choose thresholds on VALIDATION, then evaluate ONCE on TEST.

Run from project root:  python -m scripts.select_model

Rule: once you have looked at test metrics, do not go back and tune.
If you tune after seeing test results, the test set is no longer an unbiased estimate.
"""

import joblib

from app.models.artifact import save_model
from app.models.columns import split_xy
from app.models.evaluate import evaluate, threshold_for_budget
from app.models.tracking import ARTIFACT_DIR, load_splits

HIGH_BUDGET = 0.02     # top 2% -> "high" -> analyst review
MEDIUM_BUDGET = 0.05   # next 3% -> "medium" -> monitor
MIN_IMPROVEMENT = 0.01 # XGBoost must beat logreg by >= 0.01 average precision to be worth it


def main() -> None:
    train, val, test = load_splits()
    X_val, y_val = split_xy(val)
    X_test, y_test = split_xy(test)

    # 1) Compare candidates on VALIDATION only.
    candidates = {name: joblib.load(ARTIFACT_DIR / f"{name}.joblib") for name in ("logreg", "xgboost")}
    val_ap = {name: evaluate(y_val, m.predict_proba(X_val)[:, 1], 0.5)["average_precision"]
              for name, m in candidates.items()}
    chosen = "xgboost" if val_ap["xgboost"] >= val_ap["logreg"] + MIN_IMPROVEMENT else "logreg"
    print(f"validation average precision: {val_ap} -> chosen: {chosen}")
    model = candidates[chosen]

    # 2) Thresholds from VALIDATION scores, defined by analyst capacity (review budget).
    val_scores = model.predict_proba(X_val)[:, 1]
    thresholds = {
        "high": threshold_for_budget(val_scores, HIGH_BUDGET),
        "medium": threshold_for_budget(val_scores, MEDIUM_BUDGET),
    }
    val_metrics = evaluate(y_val, val_scores, thresholds["high"])

    # 3) ONE look at the untouched TEST set with the frozen model + thresholds.
    test_metrics = evaluate(y_test, model.predict_proba(X_test)[:, 1], thresholds["high"])

    save_model(
        model, name="fraud_model_v1", thresholds=thresholds,
        metrics={"validation": val_metrics, "test": test_metrics},
        extra={"algorithm": chosen, "validation_average_precision": val_ap,
               "train_end": str(train["event_time"].max()), "test_start": str(test["event_time"].min())},
        artifact_dir=ARTIFACT_DIR,
    )
    print("thresholds:", {k: round(v, 4) for k, v in thresholds.items()})
    print("validation @high:", val_metrics)
    print("TEST       @high:", test_metrics)


if __name__ == "__main__":
    main()