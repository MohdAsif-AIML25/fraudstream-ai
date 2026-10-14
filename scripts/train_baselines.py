"""Stage 5: train majority, rule and logistic-regression baselines; log each to MLflow.

Run from project root:  python -m scripts.train_baselines
View results:           mlflow ui --backend-store-uri sqlite:///mlflow.db
"""

import joblib
import mlflow

from app.models.baselines import MajorityBaseline, RuleBaseline, build_logreg
from app.models.columns import split_xy
from app.models.evaluate import evaluate, threshold_for_budget
from app.models.tracking import ARTIFACT_DIR, dataset_tags, load_splits, single_row_latency_ms, start_tracking

REVIEW_BUDGET = 0.02  # analysts can review ~2% of traffic


def main() -> None:
    train, val, test = load_splits()   # test is loaded but NOT used here: it stays untouched
    X_train, y_train = split_xy(train)
    X_val, y_val = split_xy(val)

    start_tracking("fraudstream-models")
    ARTIFACT_DIR.mkdir(exist_ok=True)

    candidates = {
        "majority": MajorityBaseline(),
        "rule": RuleBaseline(),
        "logreg": build_logreg(),
    }

    print(f"{'model':<10} {'avg_prec':>9} {'precision':>9} {'recall':>7} {'flagged':>8}")
    for name, model in candidates.items():
        with mlflow.start_run(run_name=name):
            model.fit(X_train, y_train)
            scores = model.predict_proba(X_val)[:, 1]  # column 1 = P(fraud)

            # Rule/majority scores have few distinct values, so a budget threshold can't apply; use 0.5.
            threshold = threshold_for_budget(scores, REVIEW_BUDGET) if name == "logreg" else 0.5
            metrics = evaluate(y_val, scores, threshold)
            metrics.update(single_row_latency_ms(model, X_val))

            mlflow.log_params({"model": name, "review_budget": REVIEW_BUDGET, "threshold": round(threshold, 4)})
            mlflow.set_tags(dataset_tags(train, val, test))
            mlflow.log_metrics(metrics)
            if name == "logreg":
                path = ARTIFACT_DIR / "logreg.joblib"
                joblib.dump(model, path)
                mlflow.log_artifact(str(path))

            print(f"{name:<10} {metrics['average_precision']:>9.3f} {metrics['precision']:>9.3f} "
                  f"{metrics['recall']:>7.3f} {metrics['flagged_rate']:>8.3%}")


if __name__ == "__main__":
    main()