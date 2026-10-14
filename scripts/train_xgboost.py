"""Stage 6a: train the stronger candidate (XGBoost) with early stopping; log to MLflow.

Run from project root:  python -m scripts.train_xgboost
"""

import joblib
import mlflow
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from app.models.baselines import build_preprocessor_for_trees
from app.models.columns import split_xy
from app.models.evaluate import evaluate, threshold_for_budget
from app.models.tracking import ARTIFACT_DIR, dataset_tags, load_splits, single_row_latency_ms, start_tracking

REVIEW_BUDGET = 0.02
PARAMS = {
    "n_estimators": 500,          # upper limit; early stopping picks the real number
    "max_depth": 4,               # shallow trees generalise better on small fraud counts
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "eval_metric": "aucpr",       # optimise PR-AUC, matching our main metric
    "early_stopping_rounds": 30,  # stop if validation PR-AUC doesn't improve for 30 rounds
    "random_state": 42,
}


def main() -> None:
    train, val, test = load_splits()
    X_train, y_train = split_xy(train)
    X_val, y_val = split_xy(val)

    # Imbalance: weight each fraud row by (#legit / #fraud) so the loss doesn't ignore it.
    scale_pos_weight = float((y_train == 0).sum() / max((y_train == 1).sum(), 1))

    # Fit preprocessing on TRAIN only, then transform validation with the same fitted encoder.
    prep = build_preprocessor_for_trees().fit(X_train)
    model = XGBClassifier(**PARAMS, scale_pos_weight=scale_pos_weight)
    model.fit(prep.transform(X_train), y_train,
              eval_set=[(prep.transform(X_val), y_val)], verbose=False)

    # Wrap the already-fitted parts into one pipeline: raw columns in -> score out.
    pipeline = Pipeline([("prep", prep), ("model", model)])

    start_tracking("fraudstream-models")
    with mlflow.start_run(run_name="xgboost"):
        scores = pipeline.predict_proba(X_val)[:, 1]
        threshold = threshold_for_budget(scores, REVIEW_BUDGET)
        metrics = evaluate(y_val, scores, threshold)
        metrics.update(single_row_latency_ms(pipeline, X_val))
        metrics["best_iteration"] = int(model.best_iteration)

        mlflow.log_params({**PARAMS, "scale_pos_weight": round(scale_pos_weight, 1),
                           "review_budget": REVIEW_BUDGET, "threshold": round(threshold, 4)})
        mlflow.set_tags(dataset_tags(train, val, test))
        mlflow.log_metrics(metrics)

        ARTIFACT_DIR.mkdir(exist_ok=True)
        path = ARTIFACT_DIR / "xgboost.joblib"
        joblib.dump(pipeline, path)
        mlflow.log_artifact(str(path))

    print({k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()})


if __name__ == "__main__":
    main()