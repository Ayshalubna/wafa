"""Train, calibrate and evaluate the churn model; decide whom to target."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import OFFER_COST, SAVE_RATE, SEED, VALUE_MONTHS
from .data import FEATURES


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """80% train (model selection by 5-fold CV inside it) / 20% held-out test, stratified on churn."""
    train, test = train_test_split(df, test_size=0.2, stratify=df.churned, random_state=SEED)
    return train, test


SPACE = {"max_depth": [2, 3, 4], "learning_rate": [0.02, 0.04, 0.08], "min_child_weight": [1, 5, 10, 20],
         "subsample": [0.7, 0.85, 1.0], "colsample_bytree": [0.6, 0.8, 1.0], "reg_lambda": [1.0, 5.0, 10.0],
         "gamma": [0.0, 0.5, 1.0]}


def _params(p: dict) -> dict:
    return {"objective": "binary:logistic", "eval_metric": "auc", "tree_method": "exact", "seed": SEED,
            "nthread": 4, **p}


def search(train: pd.DataFrame, n_trials: int = 30) -> tuple[dict, int, list[dict]]:
    """Random search with 5-fold CV and early stopping; returns best params, rounds and the trial log."""
    rng = np.random.default_rng(SEED)
    d = xgb.DMatrix(train[FEATURES].values, label=train.churned.values, feature_names=FEATURES)
    folds = list(StratifiedKFold(5, shuffle=True, random_state=SEED).split(train, train.churned))
    log = []
    for _ in range(n_trials):
        p = {k: v[rng.integers(len(v))] for k, v in SPACE.items()}
        p = {k: (float(v) if isinstance(v, float | np.floating) else int(v)) for k, v in p.items()}
        cv = xgb.cv(_params(p), d, num_boost_round=1500, folds=folds, early_stopping_rounds=60, verbose_eval=False)
        log.append({"params": p, "rounds": len(cv), "cv_auc": float(cv["test-auc-mean"].iloc[-1]),
                    "cv_auc_std": float(cv["test-auc-std"].iloc[-1])})
    best = max(log, key=lambda r: r["cv_auc"])
    return best["params"], best["rounds"], log


@dataclass
class Model:
    """XGBoost with log-loss is already well calibrated here (checked: ECE on the test set), so no extra calibration
    layer is fitted; adding isotonic regression on a small set made calibration worse in our experiments."""
    booster: xgb.Booster

    def margin(self, X: np.ndarray) -> np.ndarray:
        return self.booster.predict(xgb.DMatrix(X, feature_names=FEATURES), output_margin=True)

    def proba(self, X: np.ndarray) -> np.ndarray:
        return 1 / (1 + np.exp(-self.margin(X)))

    def contribs(self, X: np.ndarray) -> np.ndarray:
        """Exact TreeSHAP values in log-odds (last column = expected value)."""
        return self.booster.predict(xgb.DMatrix(X, feature_names=FEATURES), pred_contribs=True)


def fit(train: pd.DataFrame, params: dict, rounds: int) -> Model:
    d = xgb.DMatrix(train[FEATURES].values, label=train.churned.values, feature_names=FEATURES)
    return Model(xgb.train(_params(params), d, num_boost_round=rounds))


def cv_compare(train: pd.DataFrame, params: dict, rounds: int) -> dict:
    """Same 5 folds for XGBoost and the logistic-regression baseline: is the extra complexity worth it?"""
    out = {"xgboost": [], "logistic": []}
    for a, b in StratifiedKFold(5, shuffle=True, random_state=SEED + 1).split(train, train.churned):
        A, B = train.iloc[a], train.iloc[b]
        out["xgboost"].append(roc_auc_score(B.churned, fit(A, params, rounds).proba(B[FEATURES].values)))
        out["logistic"].append(roc_auc_score(B.churned, baseline(A).predict_proba(B[FEATURES])[:, 1]))
    return {k: {"mean": float(np.mean(v)), "std": float(np.std(v)), "folds": [float(x) for x in v]} for k, v in out.items()}


def baseline(train: pd.DataFrame) -> object:
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, C=1.0)).fit(train[FEATURES], train.churned)


# ------------------------------------------------------------------------------------------- metrics
def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error over equal-width bins."""
    idx = np.minimum((p * bins).astype(int), bins - 1)
    return float(sum(abs(y[idx == b].mean() - p[idx == b].mean()) * (idx == b).mean() for b in range(bins) if (idx == b).any()))


def lift_at(y: np.ndarray, p: np.ndarray, frac: float) -> tuple[float, float]:
    """Lift and recall when contacting the top `frac` of customers by score."""
    n = max(1, int(round(len(y) * frac)))
    top = np.argsort(-p, kind="stable")[:n]
    return float(y[top].mean() / y.mean()), float(y[top].sum() / y.sum())


def bootstrap_auc(y: np.ndarray, p: np.ndarray, n: int = 1000) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    vals = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() != y[i].max():
            vals.append(roc_auc_score(y[i], p[i]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    l10, r10 = lift_at(y, p, 0.10)
    l20, r20 = lift_at(y, p, 0.20)
    lo, hi = bootstrap_auc(y, p)
    return {"auc": float(roc_auc_score(y, p)), "auc_ci": [lo, hi], "pr_auc": float(average_precision_score(y, p)),
            "brier": float(brier_score_loss(y, p)), "ece": ece(y, p), "lift_top10": l10, "recall_top10": r10,
            "lift_top20": l20, "recall_top20": r20, "base_rate": float(y.mean()), "n": int(len(y))}


# ------------------------------------------------------------------------------------------- campaign
def expected_value(p: np.ndarray, monthly: np.ndarray, cost: float = OFFER_COST, save_rate: float = SAVE_RATE,
                   months: int = VALUE_MONTHS) -> np.ndarray:
    """Expected net value of sending one offer: P(churn) x save rate x revenue kept - offer cost."""
    return p * save_rate * monthly * months - cost


def realised(targeted: np.ndarray, y: np.ndarray, monthly: np.ndarray, cost: float = OFFER_COST,
             save_rate: float = SAVE_RATE, months: int = VALUE_MONTHS) -> dict:
    """Value of a targeting decision judged against what actually happened (who really churned)."""
    t = targeted.astype(bool)
    kept = save_rate * (monthly[t] * months * y[t]).sum()
    spend = cost * t.sum()
    return {"contacted": int(t.sum()), "churners_reached": int(y[t].sum()), "revenue_kept": float(kept),
            "offer_spend": float(spend), "net": float(kept - spend)}


def campaign(test: pd.DataFrame, p: np.ndarray, **kw) -> dict:
    y, m = test.churned.values, test.monthly_charges.values
    ev = expected_value(p, m, **kw)
    model = ev > 0
    rng = np.random.default_rng(SEED)
    rand = np.zeros(len(y), bool)
    rand[rng.choice(len(y), model.sum(), replace=False)] = True
    return {"model": realised(model, y, m, **kw), "random_same_size": realised(rand, y, m, **kw),
            "rule_month_to_month": realised(test.month_to_month.values == 1, y, m, **kw),
            "everyone": realised(np.ones(len(y), bool), y, m, **kw),
            "assumptions": {"offer_cost": kw.get("cost", OFFER_COST), "save_rate": kw.get("save_rate", SAVE_RATE),
                            "value_months": kw.get("months", VALUE_MONTHS)}}


def fairness(test: pd.DataFrame, rows: dict, p: np.ndarray) -> dict:
    """Performance and targeting rate by gender (not a model input) and by senior status."""
    out = {}
    gender = np.array([rows[c]["gender"] for c in test.customer_id])
    groups = {"gender": {g: gender == g for g in ("Female", "Male")},
              "senior": {"senior": test.senior.values == 1, "not senior": test.senior.values == 0}}
    ev = expected_value(p, test.monthly_charges.values) > 0
    y = test.churned.values
    for name, gs in groups.items():
        out[name] = {g: {"n": int(mask.sum()), "churn_rate": float(y[mask].mean()), "auc": float(roc_auc_score(y[mask], p[mask])),
                         "targeted_rate": float(ev[mask].mean())} for g, mask in gs.items()}
    return out


def timed(f, *a, **k):
    t0 = time.perf_counter()
    r = f(*a, **k)
    return r, time.perf_counter() - t0


def to_json(obj) -> str:
    return json.dumps(obj, indent=1, default=float)
