# Data contract — transaction event, schema version 1

Source of truth: [`app/schemas/transaction.py`](../app/schemas/transaction.py). The API, the Kafka
messages and the scoring worker all validate with this one Pydantic model, so every component agrees
on what a valid transaction is. A message that breaks the contract is rejected with **422** by the API,
or sent to the dead-letter queue by the worker.

## Fields

| Field | Type | Rules | Example |
|---|---|---|---|
| `schema_version` | int | must be `1` (optional, defaults to 1) | `1` |
| `transaction_id` | string | 1–64 chars, `A-Z a-z 0-9 _ -`; unique, used for idempotency | `txn_000123` |
| `account_id` | string | same pattern; also the Kafka message key | `acct_501` |
| `device_id` | string | same pattern | `dev_77` |
| `event_time` | datetime | **must include a timezone**; stored as UTC; at most 5 min in the future | `2026-10-11T14:20:00Z` |
| `amount_minor` | int | paise, strict integer, `0 < x ≤ 100,000,000` (₹10,00,000) | `2500000` (= ₹25,000) |
| `currency` | string | only `INR` in version 1 | `INR` |
| `merchant_category` | enum | `grocery` `electronics` `travel` `food` `fashion` `utilities` `other` | `electronics` |
| `channel` | enum | `online` `pos` `atm` `upi` | `upi` |

Strictness: unknown fields are rejected (`extra="forbid"`), the object is immutable after validation,
and surrounding whitespace in strings is stripped.

## Labels are not part of the contract

The synthetic dataset also has `is_fraud` and `fraud_scenario`. A real client never sends these, so they
are stripped before validation ([`app/data/validation.py`](../app/data/validation.py)) and before replay.

## Model features (computed, never sent by clients)

Built by one function, [`app/features/compute.py`](../app/features/compute.py), for both training
(offline) and serving (Redis). Only events **strictly before** the current one are used.

| Feature | Meaning |
|---|---|
| `prior_txn_count_5m` | transactions on this account in the previous 5 minutes |
| `prior_amount_sum_5m` | their total amount (paise) |
| `seconds_since_previous_txn` | gap to the previous transaction, capped at 30 days |
| `is_new_device` | 1 if this device was never seen on the account before |
| `amount_to_prior_average` | amount ÷ average of the account's last ≤ 20 transactions |
| `history_available` | 0 for a brand-new account (other features are neutral defaults) |
| `hour_of_day_ist` | hour in India time (0–23) |

Plus three raw fields: `amount_minor`, `merchant_category`, `channel`. The exact column order is stored
in [`artifacts_meta/fraud_model_v1.json`](../artifacts_meta/fraud_model_v1.json); the worker refuses to
start if the code and the model disagree.

## Changing the contract

Version 1 accepts only `schema_version: 1`. A breaking change (new required field, new currency)
means a new model class and `schema_version: 2`, so old producers keep working during the migration.
