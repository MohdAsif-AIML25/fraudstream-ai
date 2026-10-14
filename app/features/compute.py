"""Point-in-time feature computation, shared by training (offline) and scoring (online).

Golden rule: the features for a transaction use ONLY events that happened strictly
BEFORE it. The current transaction never sees itself, and never sees the future.

Both the offline builder (Day 2) and the Kafka worker (Day 5) call the SAME code
below. One implementation = training and serving can't silently drift apart.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

VELOCITY_WINDOW = timedelta(minutes=5)   # "recent activity" window for velocity features
MAX_HISTORY = 20                         # keep only the last 20 events per account (bounded memory in Redis)
NO_HISTORY_SECONDS = 30 * 24 * 3600.0    # 30 days: cap/default for "time since previous transaction"
IST = timezone(timedelta(hours=5, minutes=30))  # customers are in India, so "hour of day" is in IST

# Fixed order of feature names. The model relies on this list, so treat it as part of the contract.
FEATURE_NAMES = (
    "prior_txn_count_5m",
    "prior_amount_sum_5m",
    "seconds_since_previous_txn",
    "is_new_device",
    "amount_to_prior_average",
    "history_available",
    "hour_of_day_ist",
)


@dataclass(frozen=True)  # frozen = immutable, like our Transaction model
class Event:
    """The minimal facts about one transaction that features need."""

    event_time: datetime  # must be timezone-aware UTC
    amount_minor: int     # paise
    device_id: str


def compute_features(
    current: Event,
    history: list[Event],
    device_first_seen: dict[str, datetime],
) -> dict[str, float]:
    """Pure function: no database, no Redis, no pandas. Same inputs -> same outputs.

    history: earlier events of this account, oldest first, all STRICTLY before current.
    device_first_seen: device_id -> first time this account used it.
    """
    # Defensive check: if a caller passes a same-time or future event, that is leakage. Fail loudly.
    if any(e.event_time >= current.event_time for e in history):
        raise ValueError("history must contain only events strictly before the current event")

    hour_ist = float(current.event_time.astimezone(IST).hour)  # 14:20 UTC -> 19 (19:50 IST)

    # A device counts as "known" only if it was first seen strictly before now.
    first_seen = device_first_seen.get(current.device_id)
    device_known = first_seen is not None and first_seen < current.event_time

    if not history:
        # Brand-new account: no behaviour to compare against.
        # Neutral defaults + history_available=0, so the model can learn "no history" separately.
        # is_new_device=0: with no history every device is "new", so the signal carries no information.
        return {
            "prior_txn_count_5m": 0.0,
            "prior_amount_sum_5m": 0.0,
            "seconds_since_previous_txn": NO_HISTORY_SECONDS,
            "is_new_device": 0.0,
            "amount_to_prior_average": 1.0,   # "same as usual" = neutral
            "history_available": 0.0,
            "hour_of_day_ist": hour_ist,
        }

    window_start = current.event_time - VELOCITY_WINDOW
    recent = [e for e in history if e.event_time >= window_start]  # events in the last 5 minutes

    previous = history[-1]  # history is oldest-first, so the last item is the most recent
    gap = (current.event_time - previous.event_time).total_seconds()

    prior_average = sum(e.amount_minor for e in history) / len(history)

    return {
        "prior_txn_count_5m": float(len(recent)),
        "prior_amount_sum_5m": float(sum(e.amount_minor for e in recent)),
        "seconds_since_previous_txn": min(gap, NO_HISTORY_SECONDS),  # cap so outliers don't dominate
        "is_new_device": 0.0 if device_known else 1.0,
        "amount_to_prior_average": current.amount_minor / prior_average,  # 25000/400 = 62.5
        "history_available": 1.0,
        "hour_of_day_ist": hour_ist,
    }


class AccountHistory:
    """Rolling state for ONE account. Offline we keep it in memory; on Day 5 the same
    state lives in Redis (a list for events, a hash for device_first_seen)."""

    def __init__(self, max_history: int = MAX_HISTORY) -> None:
        self.events: deque[Event] = deque(maxlen=max_history)  # maxlen: oldest drops off automatically
        self.device_first_seen: dict[str, datetime] = {}

    def features_for(self, current: Event) -> dict[str, float]:
        """Compute features for `current` WITHOUT adding it (read before write)."""
        # Filter instead of trusting order: two events with the SAME timestamp must not see each other.
        prior = [e for e in self.events if e.event_time < current.event_time]
        return compute_features(current, prior, self.device_first_seen)

    def add(self, event: Event) -> None:
        """Record the event AFTER its features were computed."""
        self.events.append(event)
        # setdefault keeps the earliest first-seen time if the device appears again
        self.device_first_seen.setdefault(event.device_id, event.event_time)