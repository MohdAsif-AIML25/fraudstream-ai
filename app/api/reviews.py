"""Review queue endpoints, used by the Streamlit analyst dashboard.

  GET  /reviews?status=open&limit=50          riskiest cases first
  POST /reviews/{transaction_id}/decision     confirmed_fraud | legitimate  (once per case)
  GET  /reviews/summary                       analyst feedback -> precision per model version

Why do decisions matter for ML? Each decision is a REAL label. Over time these labels
(1) measure the model's real precision, and (2) become training data for model v2.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.review_service import CaseAlreadyDecided, CaseNotFound, decide, feedback_summary, list_cases
from app.api.schemas import DecisionRequest, FeedbackSummary, ReviewCaseResponse
from app.db.models import REVIEW_CONFIRMED_FRAUD, REVIEW_LEGITIMATE, REVIEW_OPEN, ReviewCase, TransactionRecord
from app.monitoring.metrics import REVIEW_DECISIONS

router = APIRouter(prefix="/reviews", tags=["reviews"])

ReviewStatus = Query(REVIEW_OPEN, alias="status", pattern=f"^({REVIEW_OPEN}|{REVIEW_CONFIRMED_FRAUD}|{REVIEW_LEGITIMATE})$")


def _to_response(case: ReviewCase, txn: TransactionRecord) -> ReviewCaseResponse:
    return ReviewCaseResponse(
        transaction_id=case.transaction_id, status=case.status, risk_score=case.risk_score,
        risk_band=txn.risk_band, model_version=txn.model_version, created_at=case.created_at,
        account_id=txn.account_id, amount_minor=txn.payload["amount_minor"],
        merchant_category=txn.payload["merchant_category"], channel=txn.payload["channel"],
        event_time=txn.payload["event_time"], features=txn.features,
        analyst=case.analyst, note=case.note, decided_at=case.decided_at,
    )


@router.get("", response_model=list[ReviewCaseResponse])
def get_reviews(
    status_filter: str = ReviewStatus,
    limit: int = Query(50, ge=1, le=200),  # bounded: an endpoint must never return "everything"
    session: Session = Depends(get_session),
) -> list[ReviewCaseResponse]:
    return [_to_response(case, txn) for case, txn in list_cases(session, status_filter, limit)]


@router.get("/summary", response_model=list[FeedbackSummary])
def get_summary(session: Session = Depends(get_session)) -> list[FeedbackSummary]:
    return [FeedbackSummary(**row) for row in feedback_summary(session)]


@router.post("/{transaction_id}/decision", response_model=ReviewCaseResponse)
def post_decision(transaction_id: str, body: DecisionRequest,
                  session: Session = Depends(get_session)) -> ReviewCaseResponse:
    try:
        case = decide(session, transaction_id, body.decision, body.analyst, body.note)
    except CaseNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "review case not found")
    except CaseAlreadyDecided:
        raise HTTPException(status.HTTP_409_CONFLICT, "case was already decided")

    REVIEW_DECISIONS.labels(decision=body.decision).inc()
    return _to_response(case, session.get(TransactionRecord, transaction_id))