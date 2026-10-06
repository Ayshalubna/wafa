"""The in-browser scorer (web/scorer.js) must agree with XGBoost and with the SQL feature pipeline."""
import json
import shutil
import subprocess

import numpy as np
import pytest
import xgboost as xgb

from wafa.config import ARTIFACTS, ROOT, WEB_DATA
from wafa.data import FEATURES, features_sql, raw
from wafa.explain import reasons

pytestmark = pytest.mark.skipif(shutil.which("node") is None or not (WEB_DATA / "model.json").exists(),
                                reason="needs node and a built model (python -m scripts.build)")


@pytest.fixture(scope="module")
def js():
    rows = raw()
    sample = rows[::9] + [r for r in rows if r["TotalCharges"].strip() == ""]
    payload = {"model": json.loads((WEB_DATA / "model.json").read_text()),
               "reasons": json.loads((WEB_DATA / "reasons.json").read_text()),
               "fixtures": json.loads((ROOT / "tests" / "fixtures.json").read_text()), "raws": sample}
    out = subprocess.run(["node", str(ROOT / "tests" / "js_check.js")], input=json.dumps(payload), capture_output=True,
                         text=True, check=True)
    return json.loads(out.stdout), payload


def test_margins_match_xgboost(js):
    out, p = js
    ref = np.array([f["margin"] for f in p["fixtures"]])
    assert np.abs(np.array(out["margins"]) - ref).max() < 1e-4


def test_treeshap_matches_xgboost(js):
    out, p = js
    got, ref = np.array(out["shap"]), np.array([f["shap"] for f in p["fixtures"]])
    assert np.abs(got - ref).max() < 1e-4
    assert np.abs(got.sum(1) - np.array(out["margins"])).max() < 1e-4      # SHAP values add up to the output


def test_features_match_sql(js):
    out, p = js
    ref = features_sql(p["raws"])[FEATURES].values
    assert np.abs(np.array(out["features"]) - ref).max() < 1e-9


def test_scores_and_reasons_for_raw_customers(js):
    out, p = js
    X = features_sql(p["raws"])[FEATURES].values
    booster = xgb.Booster()
    booster.load_model(ARTIFACTS / "model.json")
    d = xgb.DMatrix(X, feature_names=FEATURES)
    prob = booster.predict(d)
    contribs = booster.predict(d, pred_contribs=True)
    assert np.abs(np.array(out["probability"]) - prob).max() < 1e-5
    assert np.abs(np.array(out["rowShap"]) - contribs).max() < 1e-4
    for i, x in enumerate(X):
        assert reasons(FEATURES, x, np.array(out["rowShap"][i])) == out["reasons"][i], p["raws"][i]["customerID"]
