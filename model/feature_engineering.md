# Predictive Feature Engineering — V1

## Scope and outputs

The feature layer supports forecasting, forecast-vs-target analysis, customer
segmentation/risk research, and the inventory features currently supportable
from available data. It does not train models, assign segments or risk scores,
or create recommendations.

- Read-only source: `database/fmcg_analytics_main.duckdb`
- Additive feature store: `database/fmcg_predictive_features.duckdb`
- CSV interchange outputs and machine-readable validation report:
  `processed/features/`
- Rebuild: `.venv\Scripts\python.exe src\build_features.py --as-of-date YYYY-MM-DD`
  (the as-of date defaults to the current date)

The feature database is separate so the validated analytical database remains
unchanged. The builder reads source tables through a read-only attachment.

## Feature tables

### `feature_sales_monthly`

**Grain/key:** `MonthStart × Region × Channel × Category`; observed dimension
combinations are scaffolded across every calendar month in the complete sales
history. The scaffold is derived from Sales dimensions, not Targets.

Contains calendar attributes (`Year`, `Quarter`, `MonthNumber`, `MonthName`,
`TimeIndex`), Net Sales, Quantity, Gross Margin and Gross Margin %, Active
Customers, Transaction Count, Gross Sales, Discount Amount and weighted
Discount %, Return Amount/Quantity and Return Rate, 1/3/12-month sales lags,
1/3-month quantity lags, trailing 3-month averages, and recent-versus-prior
3-month sales/quantity trend percentages.

Returns are aggregated separately by **ReturnDate month**, Region, Channel and
Category, then joined only after aggregation. No transaction-level Sales ×
Returns join is used. Return metrics are available only through the feature
cutoff month.

### `feature_customer_monthly`

**Grain/key:** `CustomerID × AsOfMonth`; each customer's rows begin at their
first observed sales month and continue through the latest complete sales
month, including zero-activity months after first purchase.

Contains monthly Net Sales, Quantity, Gross Margin/%, transaction count,
active sales days, discount amount/%, return amount/quantity/rate, active-month
flag, last purchase date and days since purchase; sales/quantity lags;
trailing 3- and 12-month value, active-month and transaction-frequency
features; recent-vs-prior 3-month trends; trailing active-month consistency;
sales per active month; and average interval between distinct purchase days
over the trailing 12 months.

`AsOfDate` is month end. Each row's features use only transactions and returns
dated on or before that as-of date. No future outcome labels are generated.
Customer JoinDate is deliberately not used: 52,842 sales transactions for
1,292 customers precede the dimension's JoinDate, so it is not a reliable
tenure cutoff in the current data.

### `feature_inventory_risk`

**Grain/key:** `SnapshotDate × DistributorID × ProductID`.

Contains the point-in-time On Hand, In Transit, Reorder Point and Expired
Quantity; available inventory (On Hand + In Transit); snapshot freshness in
days at build time; a **current** reorder-exception flag (`On Hand < Reorder
Point`); sales quantity in the three complete calendar months before the
snapshot and the preceding three months; daily velocity based on the recent
three-month total and actual days in that interval; demand trend; and an
inventory-coverage-days proxy when its velocity denominator is positive.

Inventory is never summed across snapshot dates. The three complete demand
months end before the snapshot month, avoiding partial-month demand and
future-data leakage. Coverage is descriptive, not a stockout forecast. Sales
are assigned to distributors using the current customer-to-distributor
mapping; historical assignment changes are unavailable.

## History and validation evidence

- Sales: **2025-01-01 through 2026-09-30**, 21 consecutive calendar-complete
  months, 620,000 transactions. Each month has one source file and facts span
  the first through last calendar day. No independent ingestion manifest is
  available, so source completeness beyond this evidence is not asserted.
- Customers: all **6,500** dimension customers have Sales; customer features
  contain 136,416 as-of rows from 2025-01 through 2026-09.
- Returns: source dates extend through 2026-10-30. The as-of cutoff is
  2026-09-30; 528 later return rows are excluded from these feature tables.
- Inventory: 75,600 rows across **21 monthly snapshots**, 2025-01-31 through
  2026-09-30.
- Feature primary keys: zero null-key rows and zero duplicate key groups in
  all three tables.
- Impossible-value checks: zero negative sales/customer quantity, negative
  days-since-purchase, invalid active-month flags, negative inventory
  quantities/reorder points, negative freshness, or invalid exception flags.
- Leakage checks: zero sales lag/trailing-window mismatches, zero customer
  lag/trend/as-of mismatches, zero inventory lookback mismatches; no feature
  SQL references Targets and no promotion features are included.
- Sales feature reconciliation to `fact_sales`: exact for Net Sales
  **327,109,162,314**, Quantity **4,895,862**, Gross Margin
  **120,055,809,705**, and Discount Amount **27,258,748,686**.
- Customer-month Sales reconciliation to `fact_sales`: exact for the same
  totals.
- Returns through 2026-09-30: exact for Return Amount **3,807,688,576** and
  Return Quantity **56,981**, both in monthly and customer-month features.
- Inventory: all 21 snapshots reconcile per date to source on-hand, in-transit,
  expired and reorder-exception totals; no cross-date inventory total is used.

Expected nulls are retained rather than replaced with misleading zeros:
initial lags/trends lack history; margin/discount/return rates are undefined
for zero denominators; average purchase interval is undefined before a second
distinct purchase day; and coverage is undefined when no recent demand
velocity is available. The generated `feature_validation.json` records exact
null counts and build checks.

## Limitations and exclusions

- Twenty-one monthly observations provide only one year-over-year seasonal
  comparison at the end of history; forecast backtesting will be limited.
- Sales source months are calendar-complete by file/date-bound evidence, not
  by a separate source-system completeness manifest.
- JoinDate inconsistency prevents reliable tenure derivation from that field.
- Return features stop at the latest complete sales month to preserve an
  as-of-aligned history; later returns are not backfilled into earlier rows.
- Reorder exception is a current execution condition, not predicted risk.
  Lead times/order cadence are missing; lot/batch expiry data is missing.
  Inventory coverage and demand trend must not be presented as stockout or
  expiry predictions.
- Promotion attribution is descriptive and excluded from V1 features to avoid
  unnecessary complexity and unintended causal interpretation.
- Targets are not predictors and are not allocated below their native
  Month × Region × Channel × Category grain.
