"""Fraud analyst review queue (Streamlit).

Run (API must be running):
    streamlit run dashboard/review_app.py
Then open http://localhost:8501

The dashboard talks ONLY to the API (never directly to Postgres). Why?
  - the API owns the rules (a case is decided once, decisions are validated)
  - the dashboard needs no database password
  - the same endpoints could serve a mobile app or a CLI later

Live: with "Live updates" on, new high-risk alerts appear by themselves within a few seconds.
"""

import os
from datetime import datetime

import httpx
import pandas as pd
import streamlit as st

API_URL = os.getenv("FRAUDSTREAM_API_URL", "http://127.0.0.1:8000")
LIVE_SECONDS = 5  # how often the page checks for new alerts

st.set_page_config(page_title="FraudStream review queue", page_icon="🛡️", layout="wide")
st.title("🛡️ FraudStream review queue")


def fetch_open_cases() -> list[dict] | None:
    try:
        r = httpx.get(f"{API_URL}/reviews", params={"status": "open", "limit": 100}, timeout=5)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        st.error(f"Cannot reach the API at {API_URL} ({type(exc).__name__}). Is uvicorn running?")
        return None


def fetch_feedback_summary() -> list[dict]:
    try:
        r = httpx.get(f"{API_URL}/reviews/summary", timeout=5)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return []  # the queue matters more than the stats: never block the page on this


def send_decision(transaction_id: str, decision: str, analyst: str, note: str) -> None:
    # Saved in session_state because st.rerun() below redraws the page and would erase a normal message.
    try:
        r = httpx.post(f"{API_URL}/reviews/{transaction_id}/decision",
                       json={"decision": decision, "analyst": analyst, "note": note or None}, timeout=5)
    except httpx.HTTPError as exc:  # API went down between loading the queue and clicking
        st.session_state["flash"] = ("error", f"Decision NOT saved: cannot reach the API ({type(exc).__name__}).")
        return
    if r.status_code == 409:
        st.session_state["flash"] = ("warning", "Another analyst already decided this case.")
    elif r.is_success:
        st.session_state["flash"] = ("success", f"{transaction_id} marked as {decision.replace('_', ' ')}.")
    else:
        st.session_state["flash"] = ("error", f"API returned {r.status_code}: {r.text}")


if "flash" in st.session_state:  # show (once) the result of the last decision
    kind, message = st.session_state.pop("flash")
    getattr(st, kind)(message)

analyst = st.sidebar.text_input("Analyst name", value=st.session_state.get("analyst", ""))
st.session_state["analyst"] = analyst
live = st.sidebar.toggle("Live updates", value=True, help=f"Check for new alerts every {LIVE_SECONDS} s")
if st.sidebar.button("Refresh"):
    st.rerun()

cases = fetch_open_cases()
if cases is None:
    st.stop()  # API is down: show the error above, nothing else


@st.fragment(run_every=LIVE_SECONDS if live else None)
def watch_for_new_alerts(shown_ids: frozenset[str]) -> None:
    """Runs again on its own every LIVE_SECONDS. It redraws the WHOLE page only when the set of
    open alerts changed, so a refresh that found nothing new never wipes the note being typed."""
    try:
        r = httpx.get(f"{API_URL}/reviews", params={"status": "open", "limit": 100}, timeout=5)
        r.raise_for_status()
        latest = frozenset(c["transaction_id"] for c in r.json())
    except httpx.HTTPError:
        st.caption("Live updates paused: API not reachable.")
        return
    if latest != shown_ids:
        st.rerun()  # new alert arrived (or another analyst closed one)
    st.caption(f"{'🟢 Live' if live else '⏸ Paused'} · checked {datetime.now():%H:%M:%S}")


watch_for_new_alerts(frozenset(c["transaction_id"] for c in cases))

with st.sidebar:
    st.subheader("Model precision")
    st.caption("From analyst decisions: of the alerts checked, how many were real fraud.")
    summary = fetch_feedback_summary()
    if summary:
        st.dataframe(pd.DataFrame(summary)[["model_version", "decided", "confirmed_fraud", "precision"]],
                     hide_index=True, column_config={"precision": st.column_config.NumberColumn(format="%.2f")})
    else:
        st.caption("No decisions yet.")

st.metric("Open cases", len(cases))
if not cases:
    st.success("Queue is empty. Nothing to review.")
    st.stop()

# ---------------- queue table ----------------
table = pd.DataFrame(cases)
table["amount_inr"] = table["amount_minor"] / 100  # paise -> rupees, for humans only
st.dataframe(
    table[["transaction_id", "risk_score", "amount_inr", "merchant_category", "channel", "account_id", "event_time"]],
    hide_index=True, width="stretch",
    column_config={"risk_score": st.column_config.ProgressColumn("risk", min_value=0.0, max_value=1.0, format="%.3f"),
                   "amount_inr": st.column_config.NumberColumn("amount (₹)", format="%.2f")},
)

# ---------------- one case in detail ----------------
selected_id = st.selectbox("Case to review (highest risk first)", [c["transaction_id"] for c in cases])
case = next(c for c in cases if c["transaction_id"] == selected_id)

left, right = st.columns(2)
with left:
    st.subheader("Transaction")
    st.write({k: case[k] for k in ("account_id", "merchant_category", "channel", "event_time", "model_version")})
    st.write(f"**Amount:** ₹{case['amount_minor'] / 100:,.2f}  ·  **Risk score:** {case['risk_score']:.3f}")
with right:
    st.subheader("Why the model flagged it")
    st.caption("The exact feature values the model received.")
    st.dataframe(pd.Series(case["features"] or {}, name="value"), width="stretch")

note = st.text_input("Note (optional)", max_chars=500)
confirm_col, legit_col = st.columns(2)
if not analyst:
    st.info("Enter your name in the sidebar to record decisions.")
elif confirm_col.button("🚩 Confirm fraud", type="primary", width="stretch"):
    send_decision(selected_id, "confirmed_fraud", analyst, note)
    st.rerun()
elif legit_col.button("✅ Legitimate", width="stretch"):
    send_decision(selected_id, "legitimate", analyst, note)
    st.rerun()