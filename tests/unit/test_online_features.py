"""Online feature store tests with fakeredis (a Redis that lives in memory, no Docker needed).

The most important test is the parity test: the Redis store must produce EXACTLY the
features the model was trained on (offline build_feature_table).
"""

from datetime import datetime, timedelta, timezone

import fakeredis
import numpy as np
import pytest

from app.data.synthetic import GeneratorConfig, generate_transactions
from app.features.compute import FEATURE_NAMES, Event
from app.features.offline import build_feature_table
from app.features.online import RedisFeatureStore


def at(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 10, 11, hh, mm, ss, tzinfo=timezone.utc)


T1 = Event(at(10, 0), 50_000, "device_A")
T2 = Event(at(10, 2), 30_000, "device_A")
T3 = Event(at(10, 4, 30), 2_500_000, "device_B")


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis()


@pytest.fixture
def store(redis_client) -> RedisFeatureStore:
    return RedisFeatureStore(redis_client)


def test_t3_matches_the_day2_hand_calculation(store):
    store.add("acct_501", "t1", T1)
    store.add("acct_501", "t2", T2)
    f = store.features_for("acct_501", T3)
    assert f["prior_txn_count_5m"] == 2
    assert f["prior_amount_sum_5m"] == 80_000
    assert f["seconds_since_previous_txn"] == 150
    assert f["is_new_device"] == 1
    assert f["amount_to_prior_average"] == pytest.approx(62.5)


def test_reading_does_not_add_the_event(store):
    store.features_for("acct_501", T1)
    assert store.features_for("acct_501", T2)["history_available"] == 0  # T1 was only READ, never added


def test_add_is_idempotent_for_redelivered_messages(store):
    assert store.add("acct_501", "t1", T1) is True
    assert store.add("acct_501", "t1", T1) is False      # Kafka redelivery -> no double count
    assert store.features_for("acct_501", T2)["prior_txn_count_5m"] == 1


def test_history_is_bounded(redis_client):
    store = RedisFeatureStore(redis_client, max_history=3)
    for i in range(10):
        store.add("acct_1", f"t{i}", Event(at(9, 0) + timedelta(minutes=i), 100, "d"))
    assert redis_client.llen("fs:acct:acct_1:events") == 3  # memory per account never grows past N


def test_keys_expire(store, redis_client):
    store.add("acct_501", "t1", T1)
    ttl = redis_client.ttl("fs:acct:acct_501:events")
    assert 0 < ttl <= 30 * 24 * 3600  # a silent account is forgotten after 30 days


def test_late_event_does_not_leak_the_future(store):
    store.add("acct_501", "t3", T3)          # 10:04:30 arrives first...
    f = store.features_for("acct_501", T2)   # ...then 10:02:00 arrives late
    assert f["history_available"] == 0       # T3 is in the future relative to T2 -> ignored


def test_accounts_are_isolated(store):
    store.add("acct_A", "t1", T1)
    assert store.features_for("acct_B", T2)["history_available"] == 0


def test_redis_store_matches_offline_training_features(redis_client):
    """Training-serving parity through REAL Redis data structures (fakeredis)."""
    raw = generate_transactions(GeneratorConfig(n_accounts=40, n_days=4, seed=11))
    offline = build_feature_table(raw).set_index("transaction_id")
    store = RedisFeatureStore(redis_client)

    # Kafka order: global time order, accounts interleaved.
    for row in raw.sort_values(["event_time", "transaction_id"]).itertuples(index=False):
        event = Event(row.event_time.to_pydatetime(), int(row.amount_minor), row.device_id)
        online = store.features_for(row.account_id, event)
        store.add(row.account_id, row.transaction_id, event)

        expected = offline.loc[row.transaction_id, list(FEATURE_NAMES)].to_numpy(dtype=float)
        actual = np.array([online[name] for name in FEATURE_NAMES])
        np.testing.assert_allclose(actual, expected, err_msg=row.transaction_id)