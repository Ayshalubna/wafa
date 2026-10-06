import numpy as np

from wafa import model as M
from wafa.data import FEATURES, features_sql, load, raw
from wafa.explain import phrase, reasons


def test_data_checksum_and_shape():
    df, rows = load()
    assert len(df) == 7043 and abs(df.churned.mean() - 0.265) < 0.001
    assert not df[FEATURES].isna().any().any()


def test_blank_total_charges_for_new_customers():
    r = [x for x in raw() if x["TotalCharges"].strip() == ""]
    f = features_sql(r)
    assert len(f) == 11 and (f.total_charges == 0).all() and (f.tenure == 0).all()
    assert np.allclose(f.avg_monthly_spend, f.monthly_charges)


def test_split_is_stratified_and_disjoint():
    df, _ = load()
    tr, te = M.split(df)
    assert set(tr.customer_id).isdisjoint(te.customer_id) and len(tr) + len(te) == len(df)
    assert abs(tr.churned.mean() - te.churned.mean()) < 0.005


def test_metrics_helpers():
    y = np.array([0, 0, 1, 1])
    assert M.lift_at(y, np.array([0.1, 0.2, 0.9, 0.8]), 0.5) == (2.0, 1.0)
    assert M.ece(np.array([0, 1]), np.array([0.0, 1.0])) == 0.0


def test_expected_value_and_realised():
    ev = M.expected_value(np.array([0.5, 0.1]), np.array([100.0, 100.0]), cost=60, save_rate=0.3, months=12)
    assert np.allclose(ev, [120.0, -24.0])
    r = M.realised(np.array([1, 0, 1]), np.array([1, 1, 0]), np.array([100.0, 50.0, 80.0]), cost=60, save_rate=0.3, months=12)
    assert r == {"contacted": 2, "churners_reached": 1, "revenue_kept": 360.0, "offer_spend": 120.0, "net": 240.0}


def test_reason_phrases():
    assert phrase("month_to_month", 1, 0.4) == "Month-to-month contract"
    assert phrase("tenure", 1, 0.5) == "Only 1 month as a customer"
    assert phrase("tenure", 40, -0.5) == "Loyal for 40 months"
    assert phrase("monthly_charges", 104.651, 0.2) == "High monthly bill ($105)"
    assert phrase("monthly_charges", 29.85, -0.2) == "Moderate monthly bill ($29.85)"
    x = np.zeros(len(FEATURES))
    c = np.zeros(len(FEATURES))
    c[FEATURES.index("month_to_month")] = 0.5
    x[FEATURES.index("month_to_month")] = 1
    r = reasons(FEATURES, x, c)
    assert r["risk"][0]["text"] == "Month-to-month contract" and "12-month contract" in r["actions"][0]
