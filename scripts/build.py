"""Train, evaluate and export everything:  python -m scripts.build  (about 2 minutes on a laptop).

Writes artifacts/ (model, metrics, search log), web/data/ (what the dashboard and the in-browser scorer read) and
eval/RESULTS.md. Exits non-zero if a quality gate fails.
"""
from __future__ import annotations

import json
import shutil
import sys

import numpy as np

from wafa import model as M
from wafa.config import ARTIFACTS, ROOT, WEB_DATA
from wafa.data import FEATURES, load
from wafa.explain import REASONS, reasons

GATES = {"auc": 0.82, "ece_max": 0.05}
RAW_KEEP = ["gender", "SeniorCitizen", "Partner", "Dependents", "tenure", "PhoneService", "MultipleLines", "InternetService",
            "OnlineSecurity", "OnlineBackup", "DeviceProtection", "TechSupport", "StreamingTV", "StreamingMovies", "Contract",
            "PaperlessBilling", "PaymentMethod", "MonthlyCharges", "TotalCharges"]


def trees_for_js(booster) -> dict:
    j = json.loads(booster.save_raw("json"))
    base = float(j["learner"]["learner_model_param"]["base_score"].strip("[]"))
    trees = []
    for t in j["learner"]["gradient_booster"]["model"]["trees"]:
        trees.append({"l": t["left_children"], "r": t["right_children"], "f": t["split_indices"],
                      "t": t["split_conditions"], "c": [round(x, 4) for x in t["sum_hessian"]], "d": t["default_left"]})
    return {"features": FEATURES, "base_margin": float(np.log(base / (1 - base))), "trees": trees}


def segments(df) -> list[dict]:
    out = []
    groups = {
        "Contract": [("Month-to-month", df.month_to_month == 1), ("One year", (df.month_to_month == 0) & (df.two_year == 0)),
                     ("Two year", df.two_year == 1)],
        "Tenure": [("0–6 months", df.tenure <= 6), ("7–12", (df.tenure > 6) & (df.tenure <= 12)),
                   ("13–24", (df.tenure > 12) & (df.tenure <= 24)), ("25–48", (df.tenure > 24) & (df.tenure <= 48)),
                   ("49–72", df.tenure > 48)],
        "Internet": [("Fiber", df.fiber == 1), ("DSL", df.dsl == 1), ("None", df.no_internet == 1)],
        "Payment": [("Electronic check", df.electronic_check == 1), ("Automatic", df.auto_pay == 1),
                    ("Mailed check", (df.electronic_check == 0) & (df.auto_pay == 0))],
        "Protection add-ons (internet customers)": [
            ("None", (df.no_internet == 0) & (df.n_protection == 0)), ("1–2", (df.no_internet == 0) & df.n_protection.between(1, 2)),
            ("3–4", (df.no_internet == 0) & (df.n_protection >= 3))],
    }
    for name, parts in groups.items():
        out.append({"name": name, "groups": [{"label": lab, "n": int(m.sum()), "churn_rate": float(df.churned[m].mean())}
                                             for lab, m in parts]})
    return out


def report(r: dict) -> str:
    t, lr, cv, c = r["test"]["xgboost"], r["test"]["logistic"], r["cv"], r["campaign"]
    pct = lambda x: f"{100 * x:.0f}%"  # noqa: E731
    lines = [
        "# Wafa — evaluation results", "",
        f"IBM Telco Customer Churn ({r['data']['customers']:,} customers, {pct(r['data']['churn_rate'])} churned). "
        f"80/20 stratified split; model selection by 5-fold CV inside the 80%; every number below is on the "
        f"{t['n']:,} held-out customers. Reproduce with `python -m scripts.build`.", "",
        "## Ranking quality", "",
        "| Model | ROC-AUC (95% CI) | PR-AUC | Churners in top 10% / 20% of the list | Lift at top 10% | Calibration error (ECE) |",
        "|---|---|---|---|---|---|",
        f"| **XGBoost** (depth {r['params']['max_depth']}, {r['rounds']} trees) | **{t['auc']:.3f}** ({t['auc_ci'][0]:.3f}–{t['auc_ci'][1]:.3f}) | {t['pr_auc']:.3f} | {pct(t['recall_top10'])} / {pct(t['recall_top20'])} | {t['lift_top10']:.1f}× | {t['ece']:.3f} |",
        f"| Logistic regression (baseline) | {lr['auc']:.3f} ({lr['auc_ci'][0]:.3f}–{lr['auc_ci'][1]:.3f}) | {lr['pr_auc']:.3f} | {pct(lr['recall_top10'])} / {pct(lr['recall_top20'])} | {lr['lift_top10']:.1f}× | {lr['ece']:.3f} |",
        "",
        f"Cross-validated AUC on the training data: XGBoost {cv['xgboost']['mean']:.3f} ± {cv['xgboost']['std']:.3f}, "
        f"logistic regression {cv['logistic']['mean']:.3f} ± {cv['logistic']['std']:.3f}. **On this dataset the two are "
        "statistically tied**: churn here is driven by a few strong, mostly additive signals (contract, tenure, fiber, "
        "payment method). XGBoost is kept because it is never worse, can capture interactions between factors, "
        "and gives exact per-customer SHAP explanations; the baseline is reported so the choice can be challenged.", "",
        "## Retention campaign (the decision the model is for)", "",
        f"Contact a customer when the expected value of an offer is positive: P(churn) × save rate ({pct(c['assumptions']['save_rate'])}) × "
        f"{c['assumptions']['value_months']} months of their bill − offer cost (${c['assumptions']['offer_cost']:.0f}). "
        "Judged against who actually churned in the held-out set:", "",
        "| Strategy | Customers contacted | Churners reached | Net value |", "|---|---|---|---|",
    ]
    names = {"model": "**Model (expected value > 0)**", "rule_month_to_month": "Rule: all month-to-month",
             "random_same_size": "Random, same number of offers", "everyone": "Everyone"}
    for k, lab in names.items():
        s = c[k]
        lines.append(f"| {lab} | {s['contacted']:,} | {s['churners_reached']:,} | ${s['net']:,.0f} |")
    lines += ["", "The save rate and offer cost are assumptions, not measurements: change them in the planner on the live "
              "demo, and measure the real save rate with a holdout group before scaling.", "",
              "## Fairness check", "",
              "Gender is not a model input. Performance and targeting by group on the held-out set:", "",
              "| Group | Customers | Churn rate | AUC | Share targeted |", "|---|---|---|---|---|"]
    for gs in r["fairness"].values():
        for g, v in gs.items():
            lines.append(f"| {g} | {v['n']} | {pct(v['churn_rate'])} | {v['auc']:.3f} | {pct(v['targeted_rate'])} |")
    lines += ["", "## Top drivers (mean |SHAP|, log-odds)", "", "| Feature | Importance |", "|---|---|"]
    lines += [f"| {REASONS[f]['label']} | {v:.3f} |" for f, v in r["importance"][:10]]
    return "\n".join(lines) + "\n"


def main() -> int:
    df, rows = load()
    by_id = {r["customerID"]: r for r in rows}
    train, test = M.split(df)
    params, rounds, log = M.search(train, n_trials=30)
    cv = M.cv_compare(train, params, rounds)
    model = M.fit(train, params, rounds)
    X, y = test[FEATURES].values, test.churned.values
    p = model.proba(X)
    lr = M.baseline(train)
    res = {
        "data": {"customers": len(df), "churn_rate": float(df.churned.mean()), "train": len(train), "test": len(test)},
        "params": params, "rounds": rounds, "cv": cv,
        "test": {"xgboost": M.metrics(y, p), "logistic": M.metrics(y, lr.predict_proba(test[FEATURES])[:, 1])},
        "campaign": M.campaign(test, p), "fairness": M.fairness(test, by_id, p),
    }
    contribs = model.contribs(X)
    imp = np.abs(contribs[:, :-1]).mean(0)
    res["importance"] = sorted(zip(FEATURES, imp.tolist()), key=lambda z: -z[1])

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    model.booster.save_model(ARTIFACTS / "model.json")
    (ARTIFACTS / "metrics.json").write_text(M.to_json(res))
    (ARTIFACTS / "search_log.json").write_text(M.to_json(log))

    WEB_DATA.mkdir(parents=True, exist_ok=True)
    (WEB_DATA / "model.json").write_text(json.dumps(trees_for_js(model.booster), separators=(",", ":")))
    shutil.copy(ROOT / "wafa" / "reasons.json", WEB_DATA / "reasons.json")
    customers = []
    for i, cid in enumerate(test.customer_id):
        rr = reasons(FEATURES, X[i], contribs[i])
        customers.append({"id": cid, "p": round(float(p[i]), 4), "churned": int(y[i]),
                          "raw": {k: by_id[cid][k] for k in RAW_KEEP}, "risk": rr["risk"], "protective": rr["protective"],
                          "actions": rr["actions"]})
    customers.sort(key=lambda c: -c["p"])
    (WEB_DATA / "customers.json").write_text(json.dumps(customers, separators=(",", ":")))
    # fixtures so the JavaScript scorer is tested against XGBoost itself
    fx = [{"x": X[i].tolist(), "margin": float(model.margin(X[i:i + 1])[0]), "shap": contribs[i].tolist()} for i in range(0, len(X), 7)]
    (ROOT / "tests" / "fixtures.json").write_text(json.dumps(fx))
    summary = {k: res[k] for k in ("data", "params", "rounds", "cv", "test", "campaign", "fairness")}
    summary["importance"] = res["importance"]
    summary["segments"] = segments(df)
    (WEB_DATA / "metrics.json").write_text(M.to_json(summary))
    (ROOT / "eval").mkdir(exist_ok=True)
    (ROOT / "eval" / "RESULTS.md").write_text(report(res))
    print(report(res))

    t = res["test"]["xgboost"]
    fails = []
    if t["auc"] < GATES["auc"]:
        fails.append(f"test AUC {t['auc']:.3f} < {GATES['auc']}")
    if t["ece"] > GATES["ece_max"]:
        fails.append(f"ECE {t['ece']:.3f} > {GATES['ece_max']}")
    camp = res["campaign"]
    if not camp["model"]["net"] > max(camp["random_same_size"]["net"], camp["rule_month_to_month"]["net"], camp["everyone"]["net"]):
        fails.append("model-targeted campaign does not beat the simple strategies")
    if cv["xgboost"]["mean"] < cv["logistic"]["mean"] - 0.01:
        fails.append("XGBoost is clearly worse than the logistic baseline")
    if fails:
        print("GATE FAILED:\n  " + "\n  ".join(fails))
        return 1
    print("all quality gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
