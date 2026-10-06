-- Feature engineering for churn, in plain SQL (SQLite dialect; also runs on PostgreSQL with minor changes).
-- Input: table `customers` with the raw IBM Telco columns. Output: one numeric row per customer.
-- web/scorer.js re-implements exactly these rules for the "score a customer" form; tests check both agree.
WITH base AS (
  SELECT
    customerID                                            AS customer_id,
    CAST(tenure AS INTEGER)                               AS tenure,
    CAST(MonthlyCharges AS REAL)                          AS monthly_charges,
    CASE WHEN TRIM(TotalCharges) = '' THEN 0.0 ELSE CAST(TotalCharges AS REAL) END AS total_charges,
    CAST(SeniorCitizen AS INTEGER)                        AS senior,
    (Partner = 'Yes')                                     AS partner,
    (Dependents = 'Yes')                                  AS dependents,
    (PhoneService = 'Yes')                                AS phone,
    (MultipleLines = 'Yes')                               AS multiple_lines,
    (InternetService = 'Fiber optic')                     AS fiber,
    (InternetService = 'DSL')                             AS dsl,
    (InternetService = 'No')                              AS no_internet,
    (OnlineSecurity = 'Yes')                              AS online_security,
    (OnlineBackup = 'Yes')                                AS online_backup,
    (DeviceProtection = 'Yes')                            AS device_protection,
    (TechSupport = 'Yes')                                 AS tech_support,
    (StreamingTV = 'Yes')                                 AS streaming_tv,
    (StreamingMovies = 'Yes')                             AS streaming_movies,
    (Contract = 'Month-to-month')                         AS month_to_month,
    (Contract = 'Two year')                               AS two_year,
    (PaperlessBilling = 'Yes')                            AS paperless,
    (PaymentMethod = 'Electronic check')                  AS electronic_check,
    (PaymentMethod LIKE '%(automatic)')                   AS auto_pay,
    (Churn = 'Yes')                                       AS churned
  FROM customers
)
SELECT
  customer_id, tenure, monthly_charges, total_charges, senior, partner, dependents, phone, multiple_lines,
  fiber, dsl, no_internet, online_security, online_backup, device_protection, tech_support,
  streaming_tv, streaming_movies, month_to_month, two_year, paperless, electronic_check, auto_pay,
  -- engineered
  (phone + multiple_lines + (1 - no_internet) + online_security + online_backup + device_protection
     + tech_support + streaming_tv + streaming_movies)                     AS n_services,
  (online_security + online_backup + device_protection + tech_support)     AS n_protection,
  CASE WHEN tenure > 0 THEN total_charges / tenure ELSE monthly_charges END AS avg_monthly_spend,
  monthly_charges - CASE WHEN tenure > 0 THEN total_charges / tenure ELSE monthly_charges END
                                                                           AS price_change,
  CASE WHEN tenure <= 6 THEN 1 ELSE 0 END                                  AS new_customer,
  churned
FROM base;
