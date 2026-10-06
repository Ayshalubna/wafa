"""Loads the trained model once and scores customers (used by the API)."""
from __future__ import annotations

import json
import threading
from functools import lru_cache

import numpy as np
import xgboost as xgb

from .config import ARTIFACTS, OFFER_COST, SAVE_RATE, VALUE_MONTHS, WEB_DATA
from .data import FEATURES, features_sql
from .explain import reasons
from .model import expected_value


def band(p: float) -> str:
    return "high" if p >= 0.5 else "medium" if p >= 0.25 else "low"


class Scorer:
    def __init__(self):
        self.booster = xgb.Booster()
        self.booster.load_model(ARTIFACTS / "model.json")
        self.booster.set_param({"nthread": 1})
        self.lock = threading.Lock()
        self.metrics = json.loads((WEB_DATA / "metrics.json").read_text())
        self.customers = json.loads((WEB_DATA / "customers.json").read_text())
        self.by_id = {c["id"]: c for c in self.customers}

    def score(self, raw: dict, offer_cost: float = OFFER_COST, save_rate: float = SAVE_RATE,
              value_months: int = VALUE_MONTHS) -> dict:
        row = {"customerID": raw.get("customerID", "new"), **raw}
        x = features_sql([row])[FEATURES].values
        d = xgb.DMatrix(x, feature_names=FEATURES)
        with self.lock:
            p = float(self.booster.predict(d)[0])
            contribs = self.booster.predict(d, pred_contribs=True)[0]
        ev = float(expected_value(np.array([p]), np.array([x[0][FEATURES.index("monthly_charges")]]),
                                  offer_cost, save_rate, value_months)[0])
        return {"churn_probability": round(p, 4), "risk_band": band(p), **reasons(FEATURES, x[0], contribs),
                "offer": {"expected_value": round(ev, 2), "recommend": ev > 0,
                          "assumptions": {"offer_cost": offer_cost, "save_rate": save_rate, "value_months": value_months}},
                "features": {f: float(v) for f, v in zip(FEATURES, x[0])}}


@lru_cache(maxsize=1)
def get() -> Scorer:
    return Scorer()
