"""Check the worker's results in Postgres after a replay.

Run from project root (worker has processed some events):
    python -m scripts.score_report

Prints:
  1. how many transactions are in each lifecycle status   (are any stuck in 'queued'?)
  2. the risk-band distribution                            (is 'high' close to the ~2% budget?)
  3. open review cases, highest risk first                 (the analyst's queue)
  4. a parity check: re-score stored features with the model and compare with the saved score
     -> proves the worker used the same features + model as training
"""

import pandas as pd
from sqlalchemy import func, select

from app.config import get_settings
from app.db.models import REVIEW_OPEN, STATUS_SCORED, ReviewCase, TransactionRecord
from app.db.session import make_engine, make_session_factory
from app.models.artifact import load_model
from app.models.columns import MODEL_COLUMNS


def main() -> None:
    settings = get_settings()
    Session = make_session_factory(make_engine(settings.sqlalchemy_url))

    with Session() as s:
        # 1) GROUP BY status -> e.g. [('scored', 48), ('queued', 2)]
        print("status counts:", dict(s.execute(
            select(TransactionRecord.status, func.count()).group_by(TransactionRecord.status)).all()))

        # 2) band distribution among scored rows
        bands = dict(s.execute(select(TransactionRecord.risk_band, func.count())
                               .where(TransactionRecord.status == STATUS_SCORED)
                               .group_by(TransactionRecord.risk_band)).all())
        total = sum(bands.values()) or 1
        print("risk bands:", {b: f"{n} ({n / total:.1%})" for b, n in bands.items()})

        # 3) the review queue
        cases = s.scalars(select(ReviewCase).where(ReviewCase.status == REVIEW_OPEN)
                          .order_by(ReviewCase.risk_score.desc()).limit(10)).all()
        print(f"open review cases (top {len(cases)}):")
        for c in cases:
            print(f"  {c.transaction_id}  score={c.risk_score:.3f}")

        # 4) parity on real traffic
        rows = s.scalars(select(TransactionRecord).where(TransactionRecord.status == STATUS_SCORED)
                         .order_by(TransactionRecord.scored_at.desc()).limit(200)).all()

    if rows:
        X = pd.DataFrame([{**r.features,
                           "amount_minor": r.payload["amount_minor"],
                           "merchant_category": r.payload["merchant_category"],
                           "channel": r.payload["channel"]} for r in rows], columns=MODEL_COLUMNS)
        recomputed = load_model(settings.model_path).predict_proba(X)[:, 1]
        max_diff = max(abs(a - r.risk_score) for a, r in zip(recomputed, rows))
        print(f"parity check on {len(rows)} rows: max score difference = {max_diff:.2e}",
              "OK" if max_diff < 1e-6 else "MISMATCH -> investigate before trusting scores")


if __name__ == "__main__":
    main()