"""Database engine and session factory.

Engine  = the connection pool (one per application).
Session = one unit of work (one per HTTP request).
"""

from sqlalchemy import create_engine 
from sqlalchemy.engine import Engine 
from sqlalchemy.orm import sessionmaker 
from app.db.models import Base 

def make_engine(url:str) ->Engine:
    # pool_pre_ping: test each pooled connection before use, so a restarted Postgres
    # doesn't cause "connection closed" errors on the first request afterwards.
    return create_engine(url,pool_pre_ping=True)

def make_session_factory(engine:Engine)->sessionmaker:
    # expire_on_commit=False: objects stay readable after commit (we return them in responses).
    return sessionmaker(bind=engine,expire_on_commit=False)

def create_tables(engine:Engine)->None:
    """Create missing tables. Fine for v1; a real team would use Alembic migrations
    so that schema CHANGES (new columns) are versioned too."""
    Base.metadata.create_all(engine)


