"""Streamlit dashboard tests with Streamlit's AppTest (runs the script headless, no browser).

httpx calls are redirected to an in-process FastAPI TestClient, so the dashboard talks to the
REAL API code with a SQLite database.
"""

from pathlib import Path 
import httpx 
import pytest 
from fastapi.testclient import TestClient 
from streamlit.testing.v1 import AppTest 

from app.api.main import create_app
from tests.unit.test_api import FakePublisher
from tests.unit.test_reviews import add_case, session_factory  # noqa: F401  (pytest fixture)

APP = str(Path(__file__).resolve().parents[2] / "dashboard" / "review_app.py")  # absolute path

@pytest.fixture
def api(session_factory,monkeypatch):
    client=TestClient(create_app(session_factory=session_factory,publisher=FakePublisher()))
    client.__enter__()
    strip=lambda url:url.replace("http://127.0.0.1:8000", "")
    monkeypatch.setattr(httpx,"get",lambda url, **kw:client.get(strip(url),params=kw.get("params")))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: client.post(strip(url), json=kw.get("json")))
    yield client
    client.__exit__(None, None, None)


def test_shows_an_error_when_the_api_is_down(monkeypatch):
    def refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")
    monkeypatch.setattr(httpx, "get", refuse)
    at = AppTest.from_file(APP).run()
    assert not at.exception
    assert "Cannot reach the API" in at.error[0].value


def test_empty_queue(api):
    at=AppTest.from_file(APP).run()
    assert not at.exception
    assert at.success[0].value.startswith("Queue is empty")

def test_analyst_confirms_fraud(api, session_factory):  # noqa: F811
    add_case(session_factory, "txn_top", 0.97)
    add_case(session_factory, "txn_low", 0.40)

    at = AppTest.from_file(APP).run()
    assert at.metric[0].value == "2"
    assert at.selectbox[0].value == "txn_top"           # riskiest case selected first

    at.sidebar.text_input[0].input("asif").run()
    confirm = next(b for b in at.button if "Confirm fraud" in b.label)
    confirm.click().run()

    assert not at.exception
    assert api.get("/reviews").json()[0]["transaction_id"] == "txn_low"  # txn_top left the queue
    decided = api.get("/reviews", params={"status": "confirmed_fraud"}).json()
    assert decided[0]["analyst"] == "asif"
    assert at.metric[0].value == "1"

    