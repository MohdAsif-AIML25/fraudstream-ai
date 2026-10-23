# Model promotion — champion vs. challenger

A new model never replaces the deployed one because it "looks better". It must pass a gate:
[`app/models/promotion.py`](../app/models/promotion.py) (rules) and
[`scripts/compare_models.py`](../scripts/compare_models.py) (runs them).

```bash
python -m scripts.train_xgboost --name xgboost_v2 --max-depth 6                # 1. train a challenger
python -m scripts.compare_models --candidate artifacts/xgboost_v2.joblib       # 2. compare (exit 0 = pass, 2 = fail)
python -m scripts.compare_models --candidate artifacts/xgboost_v2.joblib \
       --promote --name fraud_model_v2                                         # 3. save as a new version, only if it passes
```

## How the comparison is fair

- Both models score the **same** test transactions (the latest 15 % by time, never used for training).
- Each model uses its **own** high-risk threshold, chosen on **validation** with the same review budget
  (top 2 %). The candidate never sees test labels before it is judged.
- Metrics are measured the same way for both: PR-AUC, recall at a fixed 1 % false-positive rate,
  estimated fraud cost and single-row p95 latency.

## The gate

| Check | Rule | Why |
|---|---|---|
| Feature contract | candidate expects exactly the columns the worker builds | otherwise it scores garbage in production |
| PR-AUC not worse | ≥ deployed − 0.005 | ranking quality, independent of thresholds |
| Recall @ 1 % FPR not worse | ≥ deployed − 0.01 | same customer friction → must catch as much fraud |
| Analyst workload | flags ≤ 3 % of traffic | the review team's capacity is ~2 % |
| Latency | single-row p95 ≤ 50 ms | real-time scoring |
| **Improvement** | lower estimated cost **or** PR-AUC ≥ deployed + 0.005 | a model that is only "not worse" isn't worth the risk of a change |

Estimated cost (paise, assumptions in `CostModel`, override with `--review-cost` / `--chargeback-fee`):
`missed fraud amount + ₹500 chargeback fee per missed fraud + ₹50 analyst time per flagged transaction`.

## Real result: deeper XGBoost (max_depth 6) vs. deployed v1

From `artifacts_meta/comparisons/xgboost_v2_vs_fraud_model_v1.json` (14,845 test transactions, 75 fraud):

| | deployed `fraud_model_v1` | candidate `xgboost_v2` |
|---|---|---|
| PR-AUC | 0.9546 | 0.9569 |
| Recall @ 1 % FPR | **0.987** | 0.973 |
| Traffic flagged | 2.38 % | 2.35 % |
| Estimated cost | ₹17,700 | ₹17,450 |
| p95 latency (1 row) | 7.4 ms | 7.5 ms |

**Decision: keep v1.** The candidate is slightly cheaper with a higher PR-AUC, but at the same 1 % false-positive
rate it catches one fewer fraud out of 75. With only 75 fraud cases, a 0.2 % PR-AUC gain is noise; losing a
caught fraud is not. (The logistic-regression baseline fails four of six checks: PR-AUC 0.762, cost ₹40,186.)

## Promoting and rolling back

`--promote` writes `artifacts/<name>.joblib` and `artifacts_meta/<name>.json`; it does not touch the running
worker. To serve the new version, set in `.env`:

```ini
MODEL_PATH=artifacts/fraud_model_v2.joblib
MODEL_META_PATH=artifacts_meta/fraud_model_v2.json
```

then `docker compose up -d --build worker` (the metadata JSON is baked into the image). Every score stores
its `model_version`, so analyst precision per version shows up in `GET /reviews/summary` and the dashboard.
**Rollback** = point both variables back to v1 and restart the worker.

## After promotion: investigator feedback

Offline metrics are a prediction; analyst decisions are the truth. `GET /reviews/summary` returns per model
version: open / confirmed fraud / legitimate cases and **precision = confirmed ÷ decided**. It only covers
high-band alerts, so it measures precision, not recall. Missed fraud shows up later as chargebacks.
