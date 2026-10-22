"""Business rules of the review queue (no HTTP here, same pattern as service.py).

Rule 1: analysts see the riskiest open cases first.
Rule 2: a case is decided ONCE. If two analysts click at the same moment, exactly one wins.
"""

from datetime import datetime,timezone 
from sqlalchemy import select,update 
from sqlalchemy.orm import Session 
from app.db.models import REVIEW_OPEN,ReviewCase,TransactionRecord


class CaseNotFound(Exception):
    pass 

class CaseAlreadyDecided(Exception):
    pass

def list_case(session:Session,status:str=REVIEW_OPEN,limit:int=50) ->list[tuple[ReviewCase,TransactionRecord]]:
    """Cases with their transaction, highest risk first."""
    query = (
        select(ReviewCase, TransactionRecord)
        .join(TransactionRecord, TransactionRecord.transaction_id == ReviewCase.transaction_id)
        .where(ReviewCase.status == status)
        .order_by(ReviewCase.risk_score.desc(), ReviewCase.created_at)
        .limit(limit)
    )
    return [(case, txn) for case, txn in session.execute(query)]  # each Row unpacks like a tuple


def decide(session:Session,transaction_id:str,decision:str,analyst:str,note:str|None) -> ReviewCase:
    # Conditional UPDATE: "change it ONLY IF it is still open". The database checks and writes in
    # one atomic step, so two simultaneous decisions cannot both succeed (no read-then-write race).
    result=session.execute(
        update(ReviewCase)
        .where(ReviewCase.transaction_id==transaction_id,ReviewCase.status==REVIEW_OPEN)

    )

    if result.rowcount==0:
        session.rollback()
        if session.get(ReviewCase,transaction_id) is None:
            raise CaseNotFound(transaction_id)
        raise CaseAlreadyDecided(transaction_id)

    session.commit()

    return session.get(ReviewCase,transaction_id)