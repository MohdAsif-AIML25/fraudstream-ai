from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

from app.schemas.transaction import TransactionInput


app = FastAPI(
    title="FraudStream AI",
    description="Day 1: transaction contract validation.",
    version="0.1.0",
)


class ValidationResponse(BaseModel):
    status: Literal["validated"] = "validated"
    persisted: bool = False
    transaction: TransactionInput


@app.get("/")
def root():
    return {
        "project": "FraudStream AI",
        "stage": "Day 1",
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "fraudstream-api",
    }


@app.post(
    "/transactions/validate",
    response_model=ValidationResponse,
)
def validate_transaction(transaction: TransactionInput):
    return ValidationResponse(transaction=transaction)