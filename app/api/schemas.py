"""Response models: what the API promises to RETURN (the request model is Transaction).

Declaring responses explicitly gives correct OpenAPI docs at /docs and stops internal
columns (like the raw payload) from leaking out by accident.
"""

from datetime import datetime
from pydantic import BaseModel 

class SubmitResponse(BaseModel):
    transaction_id: str
    status: str

class TransactionStatusResponse(BaseModel):
    transaction_id: str
    status: str 
    received_at: datetime 
    risk_score: float | None=None 
    risk_band: str | None = None
    model_version: str | None = None
    scored_at: datetime | None = None

class HealthResponse(BaseModel):
    status: str 
    database: str 
    kafka: str 
    
