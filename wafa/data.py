"""Load the raw customer table into SQLite and build features with wafa/sql/features.sql."""
from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path

import pandas as pd

from .config import DATA, DATA_SHA256, SQL

RAW_COLUMNS = ["customerID", "gender", "SeniorCitizen", "Partner", "Dependents", "tenure", "PhoneService",
               "MultipleLines", "InternetService", "OnlineSecurity", "OnlineBackup", "DeviceProtection", "TechSupport",
               "StreamingTV", "StreamingMovies", "Contract", "PaperlessBilling", "PaymentMethod", "MonthlyCharges",
               "TotalCharges", "Churn"]
FEATURES = ["tenure", "monthly_charges", "total_charges", "senior", "partner", "dependents", "phone", "multiple_lines",
            "fiber", "dsl", "no_internet", "online_security", "online_backup", "device_protection", "tech_support",
            "streaming_tv", "streaming_movies", "month_to_month", "two_year", "paperless", "electronic_check", "auto_pay",
            "n_services", "n_protection", "avg_monthly_spend", "price_change", "new_customer"]
# gender is deliberately not used as a model input (see README: fairness)


def verify(path: Path = DATA) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path == DATA and digest != DATA_SHA256:
        raise ValueError(f"unexpected data file checksum {digest}")


def raw(path: Path = DATA) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def features_sql(rows: list[dict]) -> pd.DataFrame:
    """Run the SQL feature pipeline over raw rows (dicts with the IBM Telco columns)."""
    con = sqlite3.connect(":memory:")
    cols = [c for c in RAW_COLUMNS]
    con.execute(f"CREATE TABLE customers ({', '.join(f'{c} TEXT' for c in cols)})")
    con.executemany(f"INSERT INTO customers VALUES ({', '.join('?' for _ in cols)})",
                    [[r.get(c, "No" if c == "Churn" else "") for c in cols] for r in rows])
    df = pd.read_sql_query(SQL.read_text(), con)
    con.close()
    df[FEATURES] = df[FEATURES].astype(float)
    df["churned"] = df["churned"].astype(int)
    return df


def load(path: Path = DATA) -> tuple[pd.DataFrame, list[dict]]:
    verify(path)
    rows = raw(path)
    return features_sql(rows), rows
