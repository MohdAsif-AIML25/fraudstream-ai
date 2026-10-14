"""Generator tests: reproducible, contract-valid, and actually contains fraud."""

from app.data.synthetic import GeneratorConfig, generate_transactions
from app.data.validation import validate_against_contract

SMALL = GeneratorConfig(n_accounts=100, n_days=7, seed=1)


def test_same_seed_gives_identical_data():
    assert generate_transactions(SMALL).equals(generate_transactions(SMALL))


def test_every_row_passes_the_data_contract():
    assert validate_against_contract(generate_transactions(SMALL)) == []


def test_dataset_contains_both_classes_and_scenarios():
    df = generate_transactions(GeneratorConfig(n_accounts=500, n_days=7, seed=1))
    assert 0 < df["is_fraud"].mean() < 0.2
    assert {"card_testing", "account_takeover"} <= set(df["fraud_scenario"])


def test_atm_is_never_electronics():
    df = generate_transactions(SMALL)
    assert not ((df["channel"] == "atm") & (df["merchant_category"] == "electronics")).any()