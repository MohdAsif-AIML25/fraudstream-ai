"""FastAPI dependencies shared by all routers (moved out of main.py on Day 6,
because the review router needs the same database session)."""


from collections.abc import Iterator
from fastapi import Request 
from sqlalchemy.orm import Session 
from app.streaming.producer import Publisher 

def get_session(request:Request) -> Iterator[Session]:
    session=request.app.state.session_factory()
    try:
        yield session # the endpoint runs here
    finally:
        session.close()  # always return the connection to the pool


def get_publisher(request:Request)-> Publisher:
    return request.app.state.publisher 
