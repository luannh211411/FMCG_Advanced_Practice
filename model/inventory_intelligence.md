# Inventory Risk & Coverage Intelligence V1 — Predictive Build 4

## Scope and persisted outputs

This is an explainable inventory screening framework, not a stockout or
expiry prediction model. Validated feature and analytical databases are
read-only inputs; Build 1–3 outputs, semantic model, and Power BI report are
preserved.

- Builder: `.venv\Scripts\python.exe src\build_inventory_intelligence.py --as-of-date 2026-09-30 --run-date YYYY-MM-DD`
- Read-only inputs: `database/fmcg_predictive_features.duckdb` and
  `database/fmcg_analytics_main.duckdb`
- Model version: `fmcg-inventory-intelligence-v1.0.0`
- Output: `database/fmcg_predictive_outputs.duckdb` and
  `processed/predictive/`
- `fact_inventory_risk` grain:
  `SnapshotDate × DistributorID × ProductID × ModelOrRuleVersion`
- History: **75,600 rows**, 3,600 positions in each of 21 snapshots from
  **2025-01-31 through 2026-09-30**.

The wide fact contains snapshot quantities and freshness, recent/prior demand
quantities and daily velocities, demand-history flags, On-Hand and
On-Hand-plus-In-Transit coverage, current-condition flags, analytical
pressure/excess scores and levels, primary driver, version and run date.
Separate persisted tables contain risk-support assessments, thresholds,
validation, per-snapshot signal distributions, signal transitions, threshold
sensitivity, and descriptive future-demand association.

## Supported scope

| Candidate | Support | Interpretation |
|---|---|---|
| Current reorder exception | **SUPPORTED** | Observable current flag: On Hand < Reorder Point. |
| Expired inventory condition | **SUPPORTED** | Current `ExpiredQuantity > 0` only. |
| Low coverage / replenishment pressure | **PARTIALLY SUPPORTED** | Historical-velocity and current-inventory screening; no lead-time service guarantee. |
| Excess / slow-moving | **PARTIALLY SUPPORTED** | Relative high coverage and weak/no recent demand screening; not obsolescence or write-off. |
| Future stockout risk | **NOT SUPPORTED** | Lead time, order cadence, and complete future purchase orders are unavailable. |
| Future expiry risk | **NOT SUPPORTED** | Lot/batch expiry dates and shelf-life detail are unavailable. |

## As-of formulas and history eligibility

Demand is distributor-product quantity from sales, assigned with the available
customer-to-distributor mapping. Mapping changes are not historized.
All demand windows end strictly before the inventory snapshot month.

- A prior-three-month demand window is considered fully observable from the
  **2025-04** snapshot onward; this is the first snapshot whose three complete
  demand months begin with the first available Sales month (**2025-01**).
- A prior-six-month trend window is considered fully observable from
  **2025-07** onward.
- Earlier `NoRecentDemandFlag` and coverage/trend-dependent flags remain
  null/unavailable rather than treating missing history as zero demand.
- Recent daily velocity = trailing-three-complete-month Sales Quantity divided
  by the actual number of days in those three calendar months, when the window
  is observable and velocity is positive.
- Prior daily velocity uses the preceding three complete months and their
  actual day count, when all six months are observable and demand is positive.
- Demand Trend % = `(recent-three-month quantity - prior-three-month quantity)
  / prior-three-month quantity`; null when the trend window is incomplete or
  prior demand is zero.
- On-Hand Coverage Days = `OnHandQuantity / RecentDailySalesVelocity`.
- Available Coverage Days = `(OnHandQuantity + InTransitQuantity) /
  RecentDailySalesVelocity`. This is a separate planning proxy: In Transit is
  **not** physically available stock.
- Zero On Hand, reorder exception, expired inventory, and positive In Transit
  are current conditions. Zero On Hand is not labeled lost sales; reorder
  exception is not labeled future stockout.

The current-distributor mapping is also used for the descriptive future-demand
comparison. Future outcomes never enter the inventory scores or flags.

## Thresholds and scores

Thresholds are fixed from an empirical reference period for comparable
reporting, not service-level policy: coverage quantiles use mature windows in
**2025-04–2025-12** (32,400 positions); demand trend and coverage-pressure
score thresholds use **2025-07–2025-12** (21,600 positions). Excess/slow-moving
score thresholds use 21,585 stocked positions in that same period. Historical
rows are retrospective applications of these fixed analytical thresholds,
not a prospective model backtest.

| Reference threshold | Value |
|---|---:|
| On-Hand coverage P10 / P25 | 37.04 / 93.85 days |
| On-Hand coverage P75 / P90 | 283.84 / 369.53 days |
| On-Hand + In-Transit coverage P25 | 112.06 days |
| Demand trend P25 / P75 | -19.13% / +25.38% |
| Coverage-pressure score P75 / P90 | 35 / 80 points |
| Excess/slow-moving score P75 / P90 | 40 / 65 points |

These are **analytical relative thresholds**, not lead-time or operating
policy thresholds. Mature monthly On-Hand coverage P25 varied from **88.83 to
98.59 days** across 18 snapshots (2025-04–2026-09), supporting reasonable
distribution stability in this history.

### Coverage-pressure score (0–100)

- +35 current reorder exception.
- +25 On-Hand coverage at/below its reference P25.
- +20 On-Hand-plus-In-Transit coverage at/below its reference P25.
- +20 zero On Hand with recent demand.
- +10 demand trend at/above its reference P75.
- -10 when On-Hand coverage is low but positive In Transit lifts
  On-Hand-plus-In-Transit coverage above its reference P25; score is clipped
  to [0, 100].

Medium begins at the reference score P75 (**35**); High begins at P90
(**80**); lower scores are Low. Levels are analytical severity, not
probabilities.

### Excess/slow-moving screening score (0–100)

- +40 On-Hand coverage at/above reference P75.
- +20 additional points at/above reference P90.
- +25 demand trend at/below reference P25.
- +50 when positive On Hand remains despite no recent demand.
- Cap at 100; zero On Hand is assigned score 0.

Medium begins at reference score P75 (**40**); High begins at P90 (**65**).
This screens relative inventory coverage and recent demand behavior only; it
does not estimate obsolete stock or write-off value.

Primary driver is selected with transparent priority: zero On Hand with recent
demand; reorder exception with low coverage; reorder exception; very low
coverage with rising demand; very low coverage; stocked/no recent demand; high
coverage with declining demand; existing expired inventory; medium excess
signal; relative pressure; otherwise no elevated analytical signal.

## 2026-09-30 current snapshot

All quantities below are **for this snapshot only**. There are 3,600
Distributor × Product positions:

- On Hand: **1,428,342**; In Transit: **143,687**; Expired Quantity:
  **52,189**; trailing-three-complete-month Sales Quantity: **684,662**.
- Reorder exceptions: **802** (22.28%).
- Zero On Hand: **3** (0.08%); all three had recent demand. This is not a
  lost-sales estimate.
- Expired inventory positions: **3,502** (97.28%). The high source prevalence
  is retained literally; confirm the business meaning/quality of
  `ExpiredQuantity` before using it operationally.
- Low-coverage pressure: **998** (27.72%): 307 Medium and 691 High.
- Excess/slow-moving signal: **905** (25.14%): 534 Medium and 371 High.
- No Recent Demand: **0** among mature current demand windows.

Overlapping signal populations and their associated current inventory/demand
quantities are available in `inventory_risk_signal_distribution_by_snapshot`
and the current primary-driver summary in
`inventory_intelligence_validation.json`. Sales quantity alongside a signal
is exposure context, not lost sales. No inventory valuation is available.

## Historical validation and limitations

- All 21 snapshots contain 3,600 unique Distributor × Product positions.
  Snapshot-date On Hand, In Transit, Reorder Point, Expired Quantity and
  reorder flags reconcile exactly to `fact_inventory`; no inventory total is
  summed across snapshot dates.
- Recent and prior three-month demand features reconcile exactly to
  independently re-aggregated analytical Sales for all 75,600 rows. Velocity,
  trend, coverage formulas, zero-demand handling and source freshness were
  validated. Latest snapshot freshness is 6 days at run date 2026-10-06.
- Across 72,000 consecutive position transitions, unchanged-state rates were
  66.92% for reorder exception, 93.71% for expired condition, 62.17% for
  low-coverage pressure and 69.66% for excess/slow-moving. High/Medium/Low
  pressure tier stayed unchanged in 59.52% of transitions. No Recent Demand
  had 61,200 mature transitions, all remaining inactive.
- Sensitivity on the latest snapshot: stricter P20/P80 settings yield 881
  pressure and 729 excess positions; base P25/P75 settings yield 998 and
  905; broader P30/P70 settings yield 1,112 and 1,083. High counts also vary
  (609/294 strict; 691/371 base; 752/474 broad).
- Descriptive next-three-month Sales comparisons cover 12 eligible snapshots
  (2025-07–2026-06; the latest three future months are complete in source data).
  Median future/recent demand ratios were 1.0098/0.9399/0.9727 for Low/Medium/
  High coverage pressure and 0.9535/1.0532/1.3270 for Low/Medium/High
  excess/slow-moving. These overlapping observations are non-causal and do not
  validate a stockout or slow-moving prediction; notably, the High
  excess/slow-moving group did not show lower subsequent median demand.
- Repeat builds with the same data and dates reproduce all Build 4 outputs.
  The Build 1 feature database, analytical source, and all 15 pre-existing
  Build 2/3 output tables remain unchanged.

## Claims this framework must not make

- Stockout probability, predicted stockout, stockout date, or guaranteed
  replenishment sufficiency.
- Future expiry, expiry date, shelf-life, or future expired quantity.
- Lost sales, unmet demand, excess inventory value, obsolescence, or write-off
  value.
- Causal effects of inventory signals on sales, or validated predictive
  performance for future demand.
- That In Transit is physically available or that distributor demand is
  historically assigned using historized customer-distributor relationships.
