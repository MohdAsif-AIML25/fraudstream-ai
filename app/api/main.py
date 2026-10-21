"""FastAPI application: the entry point for transactions.

Run:   uvicorn app.api.main:app --reload
Docs:  http://127.0.0.1:8000/docs

Endpoints:
  POST /transactions        validate, store, publish to Kafka -> 202 Accepted (NOT scored yet)
  GET  /transactions/{id}   lifecycle status (+ score after Day 5)
  GET  /health              are the database and Kafka reachable?
"""

from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas import HealthResponse, SubmitResponse, TransactionStatusResponse
from app.api.service import PayloadConflict, submit_transaction
from app.db.models import TransactionRecord
from app.schemas import Transaction
from app.streaming.producer import Publisher, PublishError

def create_app(session_factory: sessionmaker | None = None, publisher: Publisher | None = None) -> FastAPI:
    """App factory. Tests pass a SQLite session factory and a fake publisher;
    in production both are None and are built from .env at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Runs once at startup (before 'yield') and once at shutdown (after 'yield').
        if session_factory is None:
            # Imported here so tests never need a real Postgres or Kafka.
            from app.config import get_settings
            from app.db.session import make_engine, make_session_factory
            from app.streaming.producer import KafkaPublisher

            settings = get_settings()
            engine = make_engine(settings.sqlalchemy_url)
            create_tables(engine)
            app.state.session_factory = make_session_factory(engine)
            app.state.publisher = KafkaPublisher(settings.kafka_bootstrap_servers)
        else:
            app.state.session_factory = session_factory
            app.state.publisher = publisher
        yield
        app.state.publisher.close()  # flush buffered messages on shutdown

    app = FastAPI(title="FraudStream AI", version="0.5.0", lifespan=lifespan)

    # ---------- dependencies: FastAPI calls these and injects the results ----------

    def get_session(request: Request) -> Iterator[Session]:
        session = request.app.state.session_factory()
        try:
            yield session          # the endpoint runs here
        finally:
            session.close()        # always return the connection to the pool

    def get_publisher(request: Request) -> Publisher:
        return request.app.state.publisher

    # ---------- endpoints ----------

    @app.post("/transactions", response_model=SubmitResponse, status_code=status.HTTP_202_ACCEPTED)
    def post_transaction(
        txn: Transaction,  # FastAPI validates the body with our Day 1 contract -> 422 if invalid
        response: Response,
        session: Session = Depends(get_session),
        publisher: Publisher = Depends(get_publisher),
    ) -> SubmitResponse:
        try:
            result = submit_transaction(session, publisher, txn)
        except PayloadConflict:
            raise HTTPException(status.HTTP_409_CONFLICT, "transaction_id already used with different data")
        except PublishError:
            # 503 = "try again later". The row is saved as 'received'; a retry will publish it.
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "event store unavailable, retry later")

        if not result.created:
            response.status_code = status.HTTP_200_OK  # duplicate: nothing new was accepted
        return SubmitResponse(transaction_id=result.record.transaction_id, status=result.record.status)

    @app.get("/transactions/{transaction_id}", response_model=TransactionStatusResponse)
    def get_transaction(transaction_id: str, session: Session = Depends(get_session)) -> TransactionStatusResponse:
        record = session.get(TransactionRecord, transaction_id)
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "transaction not found")
        # model_validate(..., from_attributes=True) reads fields straight from the ORM object
        return TransactionStatusResponse.model_validate(record, from_attributes=True)

    @app.get("/health", response_model=HealthResponse)
    def health(
        response: Response,
        session: Session = Depends(get_session),
        publisher: Publisher = Depends(get_publisher),
    ) -> HealthResponse:
        try:
            session.execute(text("SELECT 1"))  # cheapest possible query
            db_ok = True
        except Exception:
            db_ok = False
        kafka_ok = publisher.healthy()

        if not (db_ok and kafka_ok):
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE  # load balancers read this code
        return HealthResponse(
            status="ok" if db_ok and kafka_ok else "degraded",
            database="ok" if db_ok else "down",
            kafka="ok" if kafka_ok else "down",
        )

    return app


app = create_app()  # what uvicorn imports; real resources are only created at startup