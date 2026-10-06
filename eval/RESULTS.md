# Wafa — evaluation results

IBM Telco Customer Churn (7,043 customers, 27% churned). 80/20 stratified split; model selection by 5-fold CV inside the 80%; every number below is on the 1,409 held-out customers. Reproduce with `python -m scripts.build`.

## Ranking quality

| Model | ROC-AUC (95% CI) | PR-AUC | Churners in top 10% / 20% of the list | Lift at top 10% | Calibration error (ECE) |
|---|---|---|---|---|---|
| **XGBoost** (depth 3, 141 trees) | **0.848** (0.826–0.868) | 0.664 | 28% / 51% | 2.8× | 0.023 |
| Logistic regression (baseline) | 0.845 (0.823–0.866) | 0.653 | 28% / 51% | 2.8× | 0.021 |

Cross-validated AUC on the training data: XGBoost 0.849 ± 0.003, logistic regression 0.849 ± 0.005. **On this dataset the two are statistically tied**: churn here is driven by a few strong, mostly additive signals (contract, tenure, fiber, payment method). XGBoost is kept because it is never worse, can capture interactions between factors, and gives exact per-customer SHAP explanations; the baseline is reported so the choice can be challenged.

## Retention campaign (the decision the model is for)

Contact a customer when the expected value of an offer is positive: P(churn) × save rate (30%) × 12 months of their bill − offer cost ($60). Judged against who actually churned in the held-out set:

| Strategy | Customers contacted | Churners reached | Net value |
|---|---|---|---|
| **Model (expected value > 0)** | 572 | 281 | $47,569 |
| Rule: all month-to-month | 773 | 329 | $37,566 |
| Random, same number of offers | 572 | 160 | $6,384 |
| Everyone | 1,409 | 374 | $13,434 |

The save rate and offer cost are assumptions, not measurements: change them in the planner on the live demo, and measure the real save rate with a holdout group before scaling.

## Fairness check

Gender is not a model input. Performance and targeting by group on the held-out set:

| Group | Customers | Churn rate | AUC | Share targeted |
|---|---|---|---|---|
| Female | 687 | 28% | 0.847 | 41% |
| Male | 722 | 25% | 0.849 | 40% |
| senior | 222 | 44% | 0.793 | 72% |
| not senior | 1187 | 23% | 0.849 | 35% |

## Top drivers (mean |SHAP|, log-odds)

| Feature | Importance |
|---|---|
| Month-to-month contract | 0.532 |
| Fiber internet | 0.317 |
| Months as a customer | 0.303 |
| Two-year contract | 0.249 |
| Pays by electronic check | 0.166 |
| Lifetime spend | 0.122 |
| Paperless billing | 0.121 |
| Monthly bill | 0.116 |
| Average monthly spend | 0.109 |
| No internet service | 0.101 |
