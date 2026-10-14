"""Synthetic transaction generator with injected fraud scenarios.

HONEST LIMITATION: the model will learn patterns that WE designed here.
Good metrics prove the engineering works, not real-world fraud performance.

Design (see docs/dataset.md):
  - Each account has 1-2 usual devices, a typical spend, favourite categories.
  - Legit noise: some legit transactions use a new device, some are big purchases,
    some accounts have legit bursts (e.g. splitting a bill). Without this noise,
    "new device = fraud" would be a perfect rule and the model would score 100%.
  - Fraud A, card testing: burst of tiny transactions within minutes.
  - Fraud B, account takeover: a few unusually large transactions in risky categories.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

CATEGORIES = ["grocery", "electronics", "travel", "food", "fashion", "utilities", "other"]
CHANNELS = ["upi", "pos", "online", "atm"]
CHANNEL_WEIGHTS = [0.40, 0.30, 0.25, 0.05]
MAX_AMOUNT_MINOR = 100_000_000  # same ceiling as the data contract (₹10,00,000)
MIN_AMOUNT_MINOR = 100          # ₹1


@dataclass(frozen=True)
class GeneratorConfig:
    """All knobs in one place. Same config + same seed -> identical dataset (reproducible)."""

    n_accounts: int = 2000
    n_days: int = 30
    start: datetime = datetime(2026, 9, 1, tzinfo=timezone.utc)
    seed: int = 42
    legit_new_device_rate: float = 0.02    # 2% of legit txns on a never-seen device
    legit_big_purchase_rate: float = 0.01  # 1% of legit txns are 5-15x the usual amount
    legit_burst_account_rate: float = 0.03 # 3% of accounts have one legit rapid burst
    card_testing_account_rate: float = 0.02
    takeover_account_rate: float = 0.03
    fraud_on_known_device_rate: float = 0.30  # some fraud uses a familiar device (e.g. stolen phone)


def _amount(rng: np.random.Generator, median_minor: float, multiplier: float = 1.0) -> int:
    """Log-normal amount around the account's median. Log-normal = mostly small, a few large."""
    value = rng.lognormal(mean=np.log(median_minor * multiplier), sigma=0.6)
    return int(np.clip(round(value), MIN_AMOUNT_MINOR, MAX_AMOUNT_MINOR))


def _random_time(rng: np.random.Generator, cfg: GeneratorConfig) -> datetime:
    """A random moment, weighted toward daytime in India (07:00-23:00 IST)."""
    day = int(rng.integers(0, cfg.n_days))
    ist_hour = int(rng.choice(np.arange(24), p=_HOUR_WEIGHTS))
    seconds = int(rng.integers(0, 3600))
    ist_midnight_utc = cfg.start + timedelta(days=day) - timedelta(hours=5, minutes=30)
    return ist_midnight_utc + timedelta(hours=ist_hour, seconds=seconds)


_raw = np.array([1, 1, 1, 1, 1, 1, 2, 4, 6, 7, 7, 7, 8, 7, 7, 7, 7, 8, 9, 9, 8, 6, 4, 2], dtype=float)
_HOUR_WEIGHTS = _raw / _raw.sum()  # probabilities must sum to 1


def _row(account, device, when, amount, category, channel, is_fraud, scenario) -> dict:
    # ATMs don't sell electronics: keep generated data business-plausible.
    if channel == "atm":
        category = "other"
    return {
        "account_id": account,
        "device_id": device,
        "event_time": when,
        "amount_minor": amount,
        "currency": "INR",
        "merchant_category": category,
        "channel": channel,
        "is_fraud": int(is_fraud),
        "fraud_scenario": scenario,
    }


def _make_profiles(rng: np.random.Generator, cfg: GeneratorConfig) -> list[dict]:
    """One profile per account: who this customer 'is'."""
    profiles = []
    for i in range(cfg.n_accounts):
        account = f"acct_{i:05d}"
        n_devices = int(rng.integers(1, 3))  # 1 or 2 usual devices
        profiles.append({
            "account_id": account,
            "devices": [f"dev_{i:05d}_{k}" for k in range(n_devices)],
            "median_minor": float(rng.uniform(10_000, 300_000)),  # usual spend: ₹100 to ₹3,000
            "favourites": list(rng.choice(CATEGORIES, size=3, replace=False)),
            "daily_rate": float(rng.uniform(0.3, 3.0)),           # avg transactions per day
        })
    return profiles


def _legit_transactions(rng, cfg, p) -> list[dict]:
    rows = []
    n = int(rng.poisson(p["daily_rate"] * cfg.n_days))
    for _ in range(n):
        device = str(rng.choice(p["devices"]))
        if rng.random() < cfg.legit_new_device_rate:  # noise: a legit customer's new phone
            device = f"dev_new_{rng.integers(1e9)}"
        multiplier = rng.uniform(5, 15) if rng.random() < cfg.legit_big_purchase_rate else 1.0
        category = str(rng.choice(p["favourites"])) if rng.random() < 0.8 else str(rng.choice(CATEGORIES))
        channel = str(rng.choice(CHANNELS, p=CHANNEL_WEIGHTS))
        rows.append(_row(p["account_id"], device, _random_time(rng, cfg),
                         _amount(rng, p["median_minor"], multiplier), category, channel, False, "none"))

    if rng.random() < cfg.legit_burst_account_rate:  # noise: legit rapid burst, usual device
        start = _random_time(rng, cfg)
        device = p["devices"][0]
        for k in range(int(rng.integers(4, 8))):
            when = start + timedelta(seconds=int(k * rng.integers(20, 60)))
            rows.append(_row(p["account_id"], device, when, _amount(rng, p["median_minor"], 0.5),
                             "food", "upi", False, "none"))
    return rows


def _fraud_device(rng, cfg, p) -> str:
    if rng.random() < cfg.fraud_on_known_device_rate:
        return str(rng.choice(p["devices"]))      # harder case: fraud from a familiar device
    return f"dev_fraud_{rng.integers(1e9)}"


def _card_testing(rng, cfg, p) -> list[dict]:
    """Fraudster checks if stolen details work: many tiny payments in a few minutes."""
    start = _random_time(rng, cfg)
    device = _fraud_device(rng, cfg, p)
    rows, when = [], start
    for _ in range(int(rng.integers(5, 16))):
        when = when + timedelta(seconds=int(rng.integers(5, 30)))
        amount = int(rng.integers(1_000, 20_000))  # ₹10 to ₹200
        rows.append(_row(p["account_id"], device, when, amount, "other", "online", True, "card_testing"))
    return rows


def _account_takeover(rng, cfg, p) -> list[dict]:
    """Fraudster controls the account: a few large purchases that resell easily."""
    start = _random_time(rng, cfg)
    device = _fraud_device(rng, cfg, p)
    rows, when = [], start
    for _ in range(int(rng.integers(1, 4))):
        when = when + timedelta(minutes=int(rng.integers(1, 10)))
        amount = _amount(rng, p["median_minor"], float(rng.uniform(5, 20)))
        category = str(rng.choice(["electronics", "travel"]))
        channel = str(rng.choice(["online", "upi"]))
        rows.append(_row(p["account_id"], device, when, amount, category, channel, True, "account_takeover"))
    return rows


def generate_transactions(cfg: GeneratorConfig = GeneratorConfig()) -> pd.DataFrame:
    """Build the full labelled dataset, sorted by time, with unique transaction IDs."""
    rng = np.random.default_rng(cfg.seed)  # ONE seeded generator -> fully reproducible
    rows: list[dict] = []
    for p in _make_profiles(rng, cfg):
        rows.extend(_legit_transactions(rng, cfg, p))
        if rng.random() < cfg.card_testing_account_rate:
            rows.extend(_card_testing(rng, cfg, p))
        if rng.random() < cfg.takeover_account_rate:
            rows.extend(_account_takeover(rng, cfg, p))

    df = pd.DataFrame(rows)
    df["event_time"] = pd.to_datetime(df["event_time"], utc=True)
    df = df.sort_values(["event_time", "account_id"], kind="mergesort").reset_index(drop=True)
    # IDs assigned AFTER sorting so they increase with time (handy for debugging)
    df.insert(0, "transaction_id", [f"txn_{i:07d}" for i in range(len(df))])
    return df