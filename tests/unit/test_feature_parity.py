"""Training-serving parity: offline batch features == one-event-at-a-time replay.

Offline: whole table, sorted per account (build_feature_table).
Online:  events arrive interleaved across accounts, the way Kafka delivers them.
If these ever disagree, the model is trained on features it will never see in production.
"""

import numpy as np

from app.data.synthetic import GeneratorConfig, generate_transactions
from app.features.compute import FEATURE_NAMES, AccountHistory, Event
from app.features.offline import build_feature_table


def test_offline_and_streaming_features_match():
    raw = generate_transactions(GeneratorConfig(n_accounts=50, n_days=5, seed=7))
    offline = build_feature_table(raw).set_index("transaction_id")

    # Streaming replay: global time order, accounts interleaved (like a Kafka topic).
    histories: dict[str, AccountHistory] = {}
    for row in raw.sort_values(["event_time", "transaction_id"]).itertuples(index=False):
        event = Event(row.event_time.to_pydatetime(), int(row.amount_minor), row.device_id)
        history = histories.setdefault(row.account_id, AccountHistory())
        online = history.features_for(event)
        history.add(event)

        expected = offline.loc[row.transaction_id, list(FEATURE_NAMES)].to_numpy(dtype=float)
        actual = np.array([online[name] for name in FEATURE_NAMES])
        np.testing.assert_allclose(actual, expected, err_msg=row.transaction_id)