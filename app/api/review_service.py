"""Business rules of the review queue (no HTTP here, same pattern as service.py).

Rule 1: analysts see the riskiest open cases first.
Rule 2: a case is decided ONCE. If two analysts click at the same moment, exactly one wins.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import REVIEW_CONFIRMED_FRAUD, REVIEW_LEGITIMATE, REVIEW_OPEN, ReviewCase, TransactionRecord


class CaseNotFound(Exception):
    pass


class CaseAlreadyDecided(Exception):
    pass


def list_cases(session: Session, status: str = REVIEW_OPEN, limit: int = 50) -> list[tuple[ReviewCase, TransactionRecord]]:
    """Cases with their transaction, highest risk first."""
    query = (
        select(ReviewCase, TransactionRecord)
        .join(TransactionRecord, TransactionRecord.transaction_id == ReviewCase.transaction_id)
        .where(ReviewCase.status == status)
        .order_by(ReviewCase.risk_score.desc(), ReviewCase.created_at)
        .limit(limit)
    )
    return [(case, txn) for case, txn in session.execute(query)]  # each Row unpacks like a tuple


def decide(session: Session, transaction_id: str, decision: str, analyst: str, note: str | None) -> ReviewCase:
    # Conditional UPDATE: "change it ONLY IF it is still open". The database checks and writes in
    # one atomic step, so two simultaneous decisions cannot both succeed (no read-then-write race).
    result = session.execute(
        update(ReviewCase)
        .where(ReviewCase.transaction_id == transaction_id, ReviewCase.status == REVIEW_OPEN)
        .values(status=decision, analyst=analyst, note=note, decided_at=datetime.now(timezone.utc))
    )
    if result.rowcount == 0:
        # Nothing changed: either the case doesn't exist, or someone decided it already.
        session.rollback()
        if session.get(ReviewCase, transaction_id) is None:
            raise CaseNotFound(transaction_id)
        raise CaseAlreadyDecided(transaction_id)
    session.commit()
    return session.get(ReviewCase, transaction_id)


def feedback_summary(session: Session) -> list[dict]:
    """Investigator feedback turned into model evaluation, per model version.

    precision = confirmed_fraud / decided: of the alerts analysts checked, how many were real fraud.
    It only covers HIGH-band transactions (only those become cases), so it says nothing about recall.
    """
    counts = session.execute(
        select(TransactionRecord.model_version, ReviewCase.status, func.count())
        .join(TransactionRecord, TransactionRecord.transaction_id == ReviewCase.transaction_id)
        .group_by(TransactionRecord.model_version, ReviewCase.status)
    ).all()
    by_model: dict[str, dict[str, int]] = {}
    for model_version, status, n in counts:
        by_model.setdefault(model_version or "unknown", {})[status] = n

    summary = []
    for model_version, c in sorted(by_model.items()):
        fraud, legit = c.get(REVIEW_CONFIRMED_FRAUD, 0), c.get(REVIEW_LEGITIMATE, 0)
        decided = fraud + legit
        summary.append({"model_version": model_version, "open": c.get(REVIEW_OPEN, 0),
                        "confirmed_fraud": fraud, "legitimate": legit, "decided": decided,
                        "precision": fraud / decided if decided else None})
    return summary
