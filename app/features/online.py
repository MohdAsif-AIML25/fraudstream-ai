"""Online feature store: the SAME rolling account state as AccountHistory, but kept in Redis.

Offline (Day 2) the state lived in a Python dict for one script run.
Online (Day 5) the worker restarts, and later several workers run, so the state must live
OUTSIDE the process. Redis is fast (sub-millisecond), in-memory, and has the exact data types
we need:

    fs:acct:{account_id}:events   LIST  of JSON events, oldest -> newest, at most MAX_HISTORY
    fs:acct:{account_id}:devices  HASH  device_id -> first-seen time (ISO string)

The feature MATH is not repeated here: we load the history from Redis and call the Day 2
compute_features(). One formula, two storage backends -> no training/serving skew.
"""

import json
from datetime import datetime, timedelta

from redis import Redis

from app.features.compute import MAX_HISTORY, Event, compute_features

KEY_PREFIX = "fs:acct"  # "fs" = feature store; a prefix keeps our keys separate from other Redis users


def _events_key(account_id: str) -> str:
    return f"{KEY_PREFIX}:{account_id}:events"


def _devices_key(account_id: str) -> str:
    return f"{KEY_PREFIX}:{account_id}:devices"


class RedisFeatureStore:
    def __init__(self, client: Redis, max_history: int = MAX_HISTORY, ttl: timedelta = timedelta(days=30)) -> None:
        self._redis = client
        self._max_history = max_history
        self._ttl_seconds = int(ttl.total_seconds())

    # ---------------- read ----------------

    def _load(self, account_id: str) -> tuple[list[tuple[str, Event]], dict[str, datetime]]:
        # pipeline = send both commands in ONE network round trip instead of two
        pipe = self._redis.pipeline(transaction=False)
        pipe.lrange(_events_key(account_id), 0, -1)
        pipe.hgetall(_devices_key(account_id))
        raw_events, raw_devices = pipe.execute()

        events = []
        for raw in raw_events:
            item = json.loads(raw)
            events.append((item["id"], Event(datetime.fromisoformat(item["t"]), int(item["a"]), item["d"])))
        devices = {_text(k): datetime.fromisoformat(_text(v)) for k, v in raw_devices.items()}
        return events, devices

    def features_for(self, account_id: str, current: Event) -> dict[str, float]:
        """Features for `current`, using ONLY events strictly before it (read before write)."""
        events, devices = self._load(account_id)
        # Sort by time: a late-arriving event may have been appended out of order.
        prior = sorted((e for _, e in events if e.event_time < current.event_time), key=lambda e: e.event_time)
        return compute_features(current, prior, devices)

    # ---------------- write ----------------

    def add(self, account_id: str, transaction_id: str, event: Event) -> bool:
        """Record the event AFTER it was scored. Returns False if it was already recorded.

        Idempotent on purpose: Kafka delivers AT LEAST once, so the same event can arrive twice
        (e.g. the worker crashed before committing its offset). Recording it twice would inflate
        prior_txn_count_5m and change future scores.
        """
        events, _ = self._load(account_id)
        if any(txn_id == transaction_id for txn_id, _ in events):
            return False

        item = json.dumps({"id": transaction_id, "t": event.event_time.isoformat(),
                           "a": event.amount_minor, "d": event.device_id})
        ev_key, dev_key = _events_key(account_id), _devices_key(account_id)

        # transaction=True -> MULTI/EXEC: all four commands apply together or not at all.
        pipe = self._redis.pipeline(transaction=True)
        pipe.rpush(ev_key, item)                             # newest at the right end
        pipe.ltrim(ev_key, -self._max_history, -1)           # keep only the last N -> bounded memory
        pipe.hsetnx(dev_key, event.device_id, event.event_time.isoformat())  # NX: keep the FIRST time seen
        pipe.expire(ev_key, self._ttl_seconds)               # silent accounts disappear automatically
        pipe.expire(dev_key, self._ttl_seconds)
        pipe.execute()
        return True

    def healthy(self) -> bool:
        try:
            return bool(self._redis.ping())
        except Exception:
            return False


def _text(value) -> str:
    """Redis returns bytes unless decode_responses=True. Accept both."""
    return value.decode("utf-8") if isinstance(value, bytes) else value