"""Quick exploratory data analysis of the raw dataset (Stage 3).

Run from project root:  python -m scripts.eda
Paste the printed numbers into docs/data_dictionary.md.
"""

import pandas as pd

df = pd.read_parquet("data/raw/transactions.parquet")
rupees = df["amount_minor"] / 100  # paise -> rupees, for human-readable output only

print("=== Size and time span ===")
print(f"rows: {len(df):,}   accounts: {df['account_id'].nunique():,}")
print(f"from {df['event_time'].min()}  to  {df['event_time'].max()}")

print("\n=== Fraud prevalence ===")
print(f"transactions: {df['is_fraud'].mean():.2%}")
print(f"accounts with any fraud: {df.groupby('account_id')['is_fraud'].max().mean():.2%}")
print(df["fraud_scenario"].value_counts())

print("\n=== Data quality ===")
print(f"missing values: {int(df.isna().sum().sum())}")
print(f"duplicate transaction_id: {int(df['transaction_id'].duplicated().sum())}")

print("\n=== Amount (₹) by label ===")
print(rupees.groupby(df["is_fraud"]).describe().round(0))

print("\n=== Transactions per account ===")
print(df.groupby("account_id").size().describe().round(1))

print("\n=== Fraud rate by channel / category ===")
print(df.groupby("channel")["is_fraud"].mean().round(4))
print(df.groupby("merchant_category")["is_fraud"].mean().round(4))