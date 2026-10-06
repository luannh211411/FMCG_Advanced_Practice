# Sales Forecast V1 — Build 2

## Scope and outputs

This is a benchmark-driven first forecast, not a production-calibrated
probability model. The Build 1 feature table and validated analytical database
are read-only inputs. No Power BI or semantic-model objects are changed.

- Rebuild: `.venv\Scripts\python.exe src\forecast_sales.py --run-date YYYY-MM-DD`
- Source cutoff: **2026-09-30**
- Forecast horizon: **2026-10 through 2026-12**
- Model version: `fmcg-sales-forecast-v1.0.0`
- Output database: `database/fmcg_predictive_outputs.duckdb`
- CSVs and audit outputs: `processed/predictive/`

## Grain, coverage, and eligibility

Forecast and target comparison grain is `ForecastMonth × Region × Channel ×
Category`. All 72 observed series have 21 monthly observations, 21 nonzero
months, and recent activity; **72/72 (100%) are eligible**. Eligibility
requires at least 18 complete monthly observations, at least 18 nonzero
months, and a nonzero observation among the latest three months. No series
fallback or target/forecast allocation was needed.

## Backtest and methods

Seven rolling origins are used: cutoffs 2025-12 through 2026-06, with 12–18
months of training at each cutoff and horizons 1–3. The training rows,
series-eligibility decision, and forecast for each origin use only data
available through that cutoff. All methods are compared on the same eligible
series. Each method has 1,512 forecast evaluations (504 per horizon), and each
horizon covers all 72 series at all seven origins.

Methods: last observed month, trailing 3-month average, linear trend fitted to
the last six months, 12-month seasonal naive, and one fixed-parameter damped
Holt exponential-smoothing candidate (`alpha=0.30`, `beta=0.10`, damping
`0.90`). Seasonal naive is computed at all origins because the 12-month lag is
available, but is diagnostic only: the 21-month history contains only one
prior annual cycle and does not establish stable annual seasonality.

Selection is global across eligible series, not per series, to avoid
overfitting with only seven backtest origins. Choose the baseline with lowest
pooled WAPE, then lower absolute bias and simpler method as tie-breakers.
Damped Holt is promoted only if it improves baseline WAPE by at least 5% and
does not worsen absolute bias by more than 2 percentage points. WAPE is
undefined when aggregate actual sales equal zero; no artificial denominator
is used. Sales forecasts below zero are floored at zero and a clipping flag is
persisted; no negative backtest or final forecasts required clipping.

## Results and final comparison

Pooled backtest results (all horizons combined):

| Method | WAPE | Bias | MAE |
|---|---:|---:|---:|
| Last observed month | 7.0581% | +0.0590% | 15,234,429.31 |
| Trailing 3-month average | **5.6729%** | +0.1363% | **12,244,593.81** |
| Linear trend (last 6 months) | 7.3600% | -0.7078% | 15,886,048.42 |
| Seasonal naive (12 months) | 5.9016% | +0.5353% | 12,738,086.28 |
| Damped Holt | 6.1535% | -2.0464% | 13,281,838.08 |

Selected trailing-average horizon results:

| Horizon | WAPE | Bias | MAE | Evaluated forecasts |
|---:|---:|---:|---:|---:|
| 1 month | 5.7513% | +0.1825% | 12,407,959.11 | 504 |
| 2 months | 5.6099% | +0.3168% | 12,086,878.95 | 504 |
| 3 months | 5.6575% | -0.0895% | 12,238,943.37 | 504 |

Metrics, coverage by method/horizon, and seven cutoff eligibility records are
persisted in `forecast_model_comparison.csv`; detailed forecasts are in
`fact_forecast_backtest.csv`. The selected method is **trailing 3-month
average**. It has lower pooled WAPE than all other selectable methods; seasonal
naive is slightly worse and is also excluded from promotion due to limited
seasonal evidence. Damped Holt did not improve on the selected baseline. No
prediction intervals are produced.

The final forecast contains 72 series for each of October, November and
December (216 rows). All 216 targets matched; none are null or zero. Aggregate
comparison:

| Forecast month | Forecast Sales | Sales Target | Forecast Target Gap | Gap % | Achievement % |
|---|---:|---:|---:|---:|---:|
| 2026-10 | 15,501,298,072.98 | 15,945,906,547 | -444,608,474.02 | -2.7882% | 97.2118% |
| 2026-11 | 15,501,298,072.98 | 16,087,245,526 | -585,947,453.02 | -3.6423% | 96.3577% |
| 2026-12 | 15,501,298,072.98 | 16,807,531,486 | -1,306,233,413.02 | -7.7717% | 92.2283% |

Gap is Forecast Sales minus Sales Target; gap percentage and achievement are
null where target is zero. The output retains the selected method, as-of date,
run date, horizon and model version.

## Limitations

Twenty-one months give only seven rolling origins with 12–18 training months,
and only one historical annual cycle. Backtest errors are useful benchmarks,
not stable guarantees of future performance. No interval estimates are
supported. A future series that fails eligibility is withheld; it is not
silently assigned an aggregate forecast. Sales targets are joined only at
Month × Region × Channel × Category.
