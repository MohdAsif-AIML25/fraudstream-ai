"""Hand-computed feature tests. Every expected value here was worked out on paper first.

Dry-run account acct_501:
  t1 10:00:00  ₹500     device_A
  t2 10:02:00  ₹300     device_A
  t3 10:04:30  ₹25,000  device_B
  t4 10:06:00  ₹200     device_A
"""

from datetime import datetime, timezone

import pytest

from app.features.compute import NO_HISTORY_SECONDS, AccountHistory, Event, compute_features


def at(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 10, 11, hh, mm, ss, tzinfo=timezone.utc)


T1 = Event(at(10, 0), 50_000, "device_A")      # amounts in paise
T2 = Event(at(10, 2), 30_000, "device_A")
T3 = Event(at(10, 4, 30), 2_500_000, "device_B")
T4 = Event(at(10, 6), 20_000, "device_A")


def replay(*events: Event) -> list[dict]:
    """Feed events one by one, exactly like the live worker will."""
    history, out = AccountHistory(), []
    for e in events:
        out.append(history.features_for(e))
        history.add(e)
    return out


def test_first_transaction_uses_no_history_defaults():
    f = replay(T1)[0]
    assert f["history_available"] == 0
    assert f["prior_txn_count_5m"] == 0
    assert f["seconds_since_previous_txn"] == NO_HISTORY_SECONDS
    assert f["is_new_device"] == 0          # no history -> "new device" carries no information
    assert f["amount_to_prior_average"] == 1.0


def test_t3_matches_hand_calculation():
    f = replay(T1, T2, T3)[2]
    assert f["prior_txn_count_5m"] == 2              # t1 and t2 are within 5 minutes
    assert f["prior_amount_sum_5m"] == 80_000        # ₹800
    assert f["seconds_since_previous_txn"] == 150    # 10:04:30 - 10:02:00
    assert f["is_new_device"] == 1                   # device_B never seen before
    assert f["amount_to_prior_average"] == pytest.approx(62.5)  # 25000 / 400


def test_t4_matches_hand_calculation():
    # Do this one on paper BEFORE reading the asserts.
    f = replay(T1, T2, T3, T4)[3]
    assert f["prior_txn_count_5m"] == 2              # window 10:01:00-10:06:00 -> t2, t3 (t1 drops out)
    assert f["prior_amount_sum_5m"] == 2_530_000     # ₹300 + ₹25,000
    assert f["seconds_since_previous_txn"] == 90     # 10:06:00 - 10:04:30
    assert f["is_new_device"] == 0                   # device_A is known
    assert f["amount_to_prior_average"] == pytest.approx(20_000 / ((50_000 + 30_000 + 2_500_000) / 3))


def test_hour_is_reported_in_ist():
    f = replay(T1)[0]                                # 10:00 UTC = 15:30 IST
    assert f["hour_of_day_ist"] == 15


def test_same_timestamp_events_do_not_see_each_other():
    a = Event(at(12, 0), 10_000, "device_A")
    b = Event(at(12, 0), 10_000, "device_X")          # identical time, different device
    fa, fb = replay(a, b)
    assert fb["history_available"] == 0               # b must not count a as "before"
    assert fb["prior_txn_count_5m"] == 0


def test_history_with_current_or_future_event_is_rejected():
    with pytest.raises(ValueError):
        compute_features(T1, [T2], {})                # T2 is AFTER T1: leakage


def test_history_is_bounded():
    history = AccountHistory(max_history=3)
    for minute in range(10):
        history.add(Event(at(9, minute), 1_000, "device_A"))
    assert len(history.events) == 3                   # oldest events dropped automatically