# Customer Segmentation and Risk V1 — Predictive Build 3

## Scope and outputs

Build 3 creates explainable outlet/customer commercial segments and separate
relative decline and inactivity risk indicators. These are descriptive and
ranking outputs, not prescribed actions or calibrated probabilities. The
validated Build 1 customer-month feature store is read-only. No semantic-model
or report changes are included.

- Builder: `.venv\Scripts\python.exe src\build_customer_intelligence.py --as-of-date 2026-09-30 --run-date YYYY-MM-DD`
- Source: `database/fmcg_predictive_features.duckdb`, table
  `feature_customer_monthly`
- Output database: `database/fmcg_predictive_outputs.duckdb`
- CSV and validation outputs: `processed/predictive/`
- Model version: `fmcg-customer-intelligence-v1.0.0`
- As-of date: **2026-09-30**

## Output grain and feature rules

`fact_customer_segment_risk` is keyed by
`CustomerID × AsOfMonth × ModelOrRuleVersion`. It retains all 136,416 customer
months, with the segment and distinct decline/inactivity scores and levels,
component scores, primary risk driver, current trailing sales/margin context,
and run/as-of dates.

All predictor features are as-of features: trailing 3/6/12-month values,
recent-versus-prior sales/quantity trends, active-month change, purchase
frequency/consistency, recency relative to purchase cadence, margin, discount,
and returns use only data on or before each AsOfMonth. Percentile ranks are
calculated within each as-of month. Return features remain separately
aggregated; returns are not joined to transaction-level sales. Targets,
promotions, future outcomes, and unobserved CRM visits/calls are not used as
predictors.

Customers require at least **6 observed customer-months** for segment/risk
scores. Earlier rows are retained with `INSUFFICIENT HISTORY` and null scores.
There are 32,500 such early-history rows across the full panel and none in the
September 2026 snapshot.

## Segmentation rules

Rules use monthly empirical score percentiles, not absolute commercial
thresholds. `CommercialQualityScore` is context only and does not gate the
segment:

- **RISK / DECLINING:** value at/above the within-month median plus momentum
  at/below P30, or engagement at/below P30 together with declining active
  months.
- **CORE / MAINTAIN:** value at/above the within-month median and not assigned
  Risk.
- **POTENTIAL:** momentum at/above P70 and engagement at/above P50.
- **LOW PRIORITY / DORMANT:** other eligible customers. This is a relative
  commercial segment, not proof of literal inactivity.
- **INSUFFICIENT HISTORY:** fewer than 6 observed customer-months.

Risk and Potential candidates require two consecutive monthly classifications
before those assignments change. Other eligible segment candidates update
directly. Segment sensitivity is reported for boundaries shifted by five score
points in either direction.

## Decline and inactivity risk

The decline outcome is measured over the next three complete months. A positive
label requires future three-month sales divided by three times the
as-of trailing-three-month monthly average to be at or below the development
period P25, and at least two of the three future monthly sales values below the
as-of baseline. Its score combines sales, quantity, and active-month trend
ranks. Score direction is selected using development data only. The High tier
uses the development-score P80 cutoff, with P50 as the Low/Medium boundary;
the cutoff is fixed for the temporal holdout. The score is not probability
calibrated.

Mature rolling outcome windows span **2025-06 through 2026-06**: four
development as-of months (**2025-06–2025-09**), three omitted months
(**2025-10–2025-12**) to avoid overlapping development/holdout outcome
windows, and six temporal-holdout months (**2026-01–2026-06**). Future data
are used only for outcome labels and validation, never predictor features.
Adjacent three-month outcomes overlap and are correlated.

The inactivity outcome requires zero transactions in the next three complete
months and a gap to the future-window end greater than the customer's
as-of trailing-12-month average purchase interval. No positive outcomes were
observed in either development or temporal holdout. The P50/P80 inactivity
tiers are therefore **provisional relative ranks, not a validated predictive
model**.

## Validation results

Temporal validation is forward-in-time, not random. Development contains
25,916 customer-month outcomes across 6,500 customers; holdout contains 39,000
across 6,500 customers.

| Decline metric | Development | Temporal holdout |
|---|---:|---:|
| Positive outcomes / observations | 6,479 / 25,916 | 9,751 / 39,000 |
| ROC-AUC | 0.6914 | 0.6914 |
| Average precision | 0.3889 | 0.3824 |
| High-tier outcome rate | 42.84% | 42.30% |
| Overall outcome rate | 25.00% | 25.00% |
| High-tier lift | 1.71× | 1.69× |
| Positive outcomes captured | 34.28% | 32.07% |

The holdout High tier covers 7,392 of 39,000 customer-month observations
(18.95%). Metrics support useful relative ranking for this defined decline
label, but not calibrated individual probabilities or guaranteed future
performance.

Inactivity: **0 positive labels** among 25,916 development and 39,000 holdout
observations. ROC-AUC, lift, and capture are undefined; do not represent the
inactivity tier as validated risk.

### September 2026 snapshot

| Commercial segment | Customers | Population | Trailing 12-month sales | Gross margin |
|---|---:|---:|---:|---:|
| Potential | 213 | 3.28% | 5,249,698,937 | 1,904,987,758 |
| Core / Maintain | 2,753 | 42.35% | 90,917,691,606 | 33,378,061,737 |
| Risk / Declining | 474 | 7.29% | 15,901,081,345 | 5,859,930,999 |
| Low Priority / Dormant | 3,060 | 47.08% | 74,707,713,378 | 27,215,310,449 |

There are 1,268 High decline-tier customers and 1,363 provisional High
inactivity-tier customers; 171 are in both groups. High decline-tier
customers represent 35,803,971,365 in trailing sales and 13,072,380,979 in
trailing gross margin. High inactivity-tier values must not be interpreted as
validated future outcomes.

Across 129,916 consecutive customer-month transitions, 78.69% retain the same
segment. Excluding transitions touching insufficient-history states,
97,416 mature transitions have 78.25% stability. Moving the segment
boundaries by ±5 score points changes 9.49% (conservative) or 11.66% (broader)
of current customer assignments; these are sensitivity scenarios, not
alternative selected rules.

## Persisted audit outputs

The output database and corresponding CSVs include `fact_customer_segment_risk`,
`customer_segment_validation_summary`, `customer_segment_transition_matrix`,
`customer_segment_transition_by_month`, `customer_segment_threshold_config`,
`customer_risk_validation_results`, `customer_risk_threshold_config`,
`customer_risk_backtest`, `customer_segment_sensitivity`, and
`customer_intelligence_validation`.

Output grain uniqueness, non-null keys and segment completeness passed.
All 136,416 output rows match one-to-one to the source customer-month feature
keys, and Net Sales and trailing-12-month Sales reconcile exactly for every
row. September 2026 Net Sales total 14,896,890,533 and trailing-12-month Sales
total 186,776,185,266 in both source and output. Decline and eligible
inactivity scores are complete for all eligible rows.
The feature database is unchanged; Build 2 forecast and target-gap tables were
preserved.

## Limitations and exclusions

- Only 21 months of customer history are available; temporal validation has a
  short development period and overlapping future windows.
- Decline labels are relative to the training period and are not calibrated
  probabilities.
- Inactivity has no observed positive validation examples and is not validated.
- Segment and risk scores are within-month relative ranks; customer
  assignments/tenure are not historized.
- No visits/calls/CRM activity, forecast models, recommendations, inventory
  risk scores, DAX, or Power BI visuals are created in this milestone.
