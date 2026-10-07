# Metric, Score & Matrix Dictionary

This dictionary records the implemented definitions and their safe
interpretation. Monetary examples use the model's existing currency
formatting. The reporting period/filter context always applies unless an
as-of or snapshot date is stated.

## Metrics and rules

### Sales, growth, targets, and profitability

| Indicator | Implemented calculation / grain | Interpretation, example, and what it does not mean |
|---|---|---|
| Net Sales | `SUM(Sales[Net Sales])`; transaction rows filtered through shared dimensions. | Sales after recorded discounts. Project validation records total Net Sales of **$327.109B** over the available Sales history. Not gross sales or cash collected. |
| Gross Sales | `SUM(Sales[Gross Sales])`; transaction grain. | Sales before discount. Supports discount-rate denominator; not the post-discount sales result. |
| Quantity | `SUM(Sales[Quantity])`; transaction grain. | Units sold in the selected context. Do not compare without considering mix and time. |
| Sales Growth | MoM: `(current Net Sales − previous calendar-month Net Sales) / previous calendar-month Net Sales`; previous month uses `DATEADD(Date, -1, MONTH)`. | Positive means higher sales than the comparable previous month. Blank when the denominator/comparison is unavailable; not causal growth. |
| Target | Sum the hidden target value after applying selected Month, Region, Channel, and Category through conformed dimensions; native grain is **Month × Region × Channel × Category**. | Target must not be joined to transaction-level Sales directly. It is not a customer/outlet target. |
| Target Achievement | `Net Sales / Sales Target`; align actuals and target at native target grain first. | 100% means sales equal target. Example Q4 forecast achievement is 95.22%. Not a forecast-confidence measure. |
| Target Variance / Gap | Actual target variance: `Net Sales − Sales Target`. Forecast gap: `ForecastSales − SalesTarget`; gap % is gap/target and projected achievement is forecast/target. Ratios are blank when target is zero. | Negative indicates below target. Q4 net forecast gap is **-$2.337B**. Gap does not identify cause, loss, or recovery. |
| Gross Margin | `SUM(Sales[Gross Margin])`, where transaction Gross Margin is Net Sales less COGS. | Dollar margin in the selected context; project validated **$120.056B** and 36.70% overall. Not net profit after operating expenses. |
| Gross Margin % | `Total Gross Margin / Total Net Sales`. | Margin share of net sales; aggregate ratios should use aggregate totals, not average row percentages. |
| Active Customers | `DISTINCTCOUNT(Sales[Customer ID])` in the selected filter context. | Distinct customers with sales in context. Not number of transactions, visits, or total customer master records. |
| Return Rate % | `Total Return Amount / Total Net Sales`, with Returns kept as a separate fact and aligned to the selected date/customer/product context. | Project validated $3.900B return amount, about 1.19% of Net Sales. Not a reason to subtract Returns from sales a second time or join return rows to transaction rows. |
| Average Selling Price (ASP) | `Total Net Sales / Total Quantity`. | Aggregate net sales per unit. Example: compare ASP and Quantity together to distinguish price/mix from volume signals. Not the unweighted mean of transaction or SKU prices. |
| Quantity Growth | MoM: `(current Quantity − previous calendar-month Quantity) / previous-month Quantity`. | Positive is more units than the prior month. Does not show whether price/mix or margin improved. |
| Weighted Discount % | `Total Discount Amount / Total Gross Sales`. | Sales-weighted discount rate; validated overall value is 7.69%. Not the simple average of transaction discount percentages, nor a causal promotion-lift estimate. |

### Forecast and backtest

| Indicator | Implemented calculation / grain | Interpretation, example, and what it does not mean |
|---|---|---|
| Forecast | Selected global trailing-three-month average; forecast at Forecast Month × Region × Channel × Category, as of 2026-09-30. 72 series × 3 months = 216 rows. | A reproducible benchmark for Oct–Dec 2026, not a prediction guarantee. No interval estimates are produced. |
| Forecast Gap | `Forecast Sales − Sales Target`, joined at native target grain only. | Q4 forecast $46.504B vs target $48.841B, gap -$2.337B. Positive intersections offset negative intersections in the net total; do not call those offsets realized recovery. |
| Forecast Achievement | `Forecast Sales / Sales Target`; blank if target is zero. | Projected Q4 achievement 95.22%; monthly values are October 97.21%, November 96.36%, December 92.23%. Not probability of hitting target. |
| WAPE | `SUM(ABS(Forecast − Actual)) / ABS(SUM(Actual))`; unavailable if aggregate actual total is zero. | Selected method pooled WAPE **5.6729%** over 1,512 rolling-origin evaluations. A historical benchmark, not future error certainty. |
| Bias | `SUM(Forecast − Actual) / SUM(Actual)`; unavailable if actual total is zero. Positive means aggregate over-forecast; negative means under-forecast. | Selected method Bias **+0.1363%**. Not a confidence interval or per-series guarantee. |
| MAE | `AVERAGE(ABS(Forecast − Actual))` over evaluated forecasts. | Selected method pooled MAE **12,244,593.81** in model sales units. Scale depends on the evaluated series and aggregation. |

### Customer scores and commercial segments

Customer intelligence is an as-of panel at Customer × AsOfMonth (with model
version in the persisted output). The September 2026 values below use only
the saved 2026-09 snapshot.

**Scoring lineage:** source Sales/customer history → customer-month
features, including trailing-12-month Sales and Gross Margin; trailing-three-
month Sales/Quantity trends; active-month trend; recency/cadence; purchase
frequency, consistency, and active months → within-AsOfMonth percentile
ranks (reverse direction for Recency/Cadence) → mean of the specified
component ranks → Momentum/Engagement and value/risk features → segment or
validated risk tier. Scores compare customers in the same as-of population;
they are not absolute thresholds or directly comparable to currency.

| Indicator | Implemented calculation / rule | Interpretation, example, and what it does not mean |
|---|---|---|
| Momentum Score | For each AsOfMonth, mean of percentile ranks (0–100) of Recent Sales Trend %, Recent Quantity Trend %, and Active Month Trend; average ranks handle ties, higher is better, and finite available components are averaged. | Measures relative recent direction, not sales size or guaranteed future growth. Outlet 00955 saved September score: **76.9769**, not the requested ~99.94. |
| Engagement Score | For each AsOfMonth, mean of percentile ranks of inverse Recency/Cadence Ratio, Purchase Frequency over trailing 3 months, Purchase Consistency over trailing 6, and Active Months over trailing 6; higher frequency/consistency/activity and lower recency/cadence ratio rank better. | Relative purchase engagement, not CRM visits/calls or absolute customer commitment. Outlet 00955 saved September score: **54.5173**, not the requested ~24.90. |
| Commercial Segment | Eligible after at least 6 customer-months. Within-month empirical cutoffs: Value P50, Momentum P30/P70, Engagement P30/P50. Risk/Declining: value ≥P50 and (momentum ≤P30 or engagement ≤P30 with declining active months). Core/Maintain: value ≥P50 after Risk rule. Potential: momentum ≥P70 and engagement ≥P50 after earlier rules. Otherwise Low Priority/Dormant. Risk and Potential changes require two consecutive monthly candidates. | Relative portfolio grouping, not an absolute customer grade. Potential is not an uplift forecast; Low Priority/Dormant is not proof of literal inactivity. |
| Decline Risk | As-of sales, quantity, and active-month trend ranks form a relative score; score direction is selected on development outcomes only. High tier uses development P80; P50 separates Low from Medium. The validated label uses the next three complete months relative to an as-of trailing-three-month sales baseline and requires at least two months below baseline. | Useful relative ranking for the defined decline outcome, not a calibrated probability. Holdout High-tier rate 42.30% vs 25.00% overall (1.69× lift). |
| Inactivity Risk | Relative recency/frequency/consistency/active-month ranking, evaluated separately. | No positive inactivity outcomes were observed in development or holdout. Tiers are provisional and are not validated predictive risk or an independent action trigger. |

#### Outlet 00955 worked example and reconciliation

The saved customer dimension maps **Outlet 00955** to Customer ID `C000955`
(North, GT). Its persisted September 2026 customer record is:

- Segment: **POTENTIAL**
- Momentum: **76.9769**
- Engagement: **54.5173**
- T12M Sales: **$28,065,919** (approximately **$28.07M**)
- T12M Gross Margin: **$10,057,470**

The supplied expected Momentum (~99.94) and Engagement (~24.90) do **not**
match this saved as-of record. The requested Priority Score, High band, and
Potential T12M exposure do reconcile to the persisted action row below.
No upstream scoring was rerun to force the mismatched component values.

### Prescriptive score, exposure, and review logic

Action grain is mixed by action type: target gap at Month × Region × Channel
× Category; customer actions at Customer; inventory actions at Snapshot Date
× Distributor × Product. Scores normalize unlike measures to 0–100 within
the relevant action cohort.

**Action lineage:** saved Q4 forecast joined to Targets at native grain;
customer segment/risk and T12M/recent-sales evidence; inventory snapshot and
trailing demand → deterministic eligibility/action type → component inputs
and cohort normalization → fixed component weights → Priority Score and
fixed band → deterministic Primary Driver and action-type template. The
queue does not allocate customer targets, invent inventory quantities, or
estimate causal recovery.

| Indicator | Exact implemented calculation / rule | Interpretation, example, and what it does not mean |
|---|---|---|
| Commercial Impact | Within-action-cohort percentile (average-rank percentile): absolute negative gap for gap actions; T12M Sales for each customer action cohort; trailing-three-complete-month demand quantity for eligible inventory positions. | Comparable ranking scale, not money. Outlet 00955 Potential action: **95.4248**. |
| Risk / Opportunity Severity | Gap: `MIN(ABS(ForecastTargetGapPct) × 100, 100)`. Core/High decline: 100. Potential: `MIN((Momentum + Engagement)/2, 100)`. Inventory: `MIN(MAX(CoveragePressureScore, 65 if reorder exception else 0), 100)`. | Severity/context input, not probability. Outlet 00955: **65.7471**, the mean of its saved Momentum and Engagement. |
| Q4 Relevance | Gap action: 100. Customer action: `Q4GapRelevantSalesShare × 100`, clipped to 0–100. Inventory: `60 + 40 × category gross-negative-gap magnitude / largest category magnitude`. | Measures alignment to Q4 review scope, not causality. Outlet 00955: **50.7089**. |
| Evidence Confidence | Fixed governance anchors: gap 72; validated High decline 80; Potential 65; reorder exception 85; coverage-pressure screening 70. | Explicit evidence-strength judgment, not statistical confidence or confidence interval. |
| Actionability | Fixed review anchors: native-grain gap 90; account-team review 75; normal-policy inventory review 80. | Practical review readiness, not likelihood the action will succeed. |
| Priority Score | `ROUND(CommercialImpact×0.30 + Severity×0.25 + Q4Relevance×0.20 + EvidenceConfidence×0.15 + Actionability×0.10, 4)`. | Weighted prioritization score, not dollars, risk probability, or expected recovery. |
| Priority Level | Critical ≥80; High ≥65 and <80; Medium ≥45 and <65; Low <45. | Outlet 00955 persisted score **72.456**, displayed to one decimal as **72.5**, therefore **High**. |
| Core High Decline 12M Sales Exposure | Distinct Customer IDs among `CORE_HIGH_DECLINE_REVIEW`; sum each customer's maximum T12M Sales once. | **617 customers; $20.177B** T12M sales. Existing business exposure, not expected loss or recoverable value. |
| Potential 12M Sales Exposure | Eligible customer action requires Commercial Segment `POTENTIAL`, Momentum ≥70, Engagement ≥50, and positive T12M Sales. Distinct Customer IDs among `POTENTIAL_GROWTH_VALIDATION`; sum each customer's maximum T12M Sales once. | **153 customers; $3.764B** T12M sales. Outlet 00955 contributes $28,065,919 of current T12M sales; not incremental sales opportunity. |
| Q4-gap-relevant recent sales | For Jul–Sep 2026 sales by Customer × Category, map customer using current Region/Channel and Category from transactions; include sales when that Region × Channel × Category has a negative Q4 gap. Share = relevant recent sales / all recent sales. Cohort DAX deduplicates customers and sums `MAX(Recent 3-Month Sales) × MAX(Q4-Gap-Relevant Sales Share)`. | Core/High: **$1.919B** of $6.716B recent sales; Potential: **$0.465B** of $1.416B. Recent mapped sales are context, not recoverable revenue. Customer geography history is unavailable. |
| Coverage Pressure | Analytical 0–100 screening score: +35 reorder exception; +25 low On-Hand coverage; +20 low On-Hand-plus-In-Transit coverage; +20 zero On Hand with recent demand; +10 rising demand; -10 when In Transit lifts combined coverage above threshold; clip to 0–100. Medium begins at 35 and High at 80 in the inventory model. | Screening evidence only; does not include validated replenishment lead time/service-level probability. |
| Reorder Exception | Current snapshot condition: `On Hand Quantity < Reorder Point`. | A current execution exception, not a forecasted stockout. |
| Primary Driver | Deterministic Power Query mapping: gap → “Projected forecast below target”; Core/High → “Validated High decline-risk tier”; Potential → “Momentum and engagement qualification”; otherwise reorder flag → “On Hand below Reorder Point”; else → “Coverage pressure with recent demand”. | Short explanation of the current rule branch, not causal diagnosis. |
| Recommendation Template | Fixed action-type text: gap review validates local drivers and owner; Core/High reviews observed trend/account context; Potential validates signals, interest, and capacity; inventory reviews On Hand, Reorder Point, recent demand, and inbound status under normal policy. | Suggested investigation only. No LLM free-form recommendation, exact order quantity, or estimated recovery. |

Outlet 00955 Priority Score calculation from its persisted action row:

`95.4248366×0.30 + 65.7471154×0.25 + 50.7089153×0.20 + 65×0.15 + 75×0.10 = 72.456`

Rounded for display: **72.5 → High**. Its saved recommendation asks the
account team to validate observed momentum and engagement, customer interest,
and capacity before recording an opportunity.

## Matrix and table reading guide

For every view, use the page's actual filters and native grain; the visual
does not authorize an unsupported allocation.

### 1. Region → Channel → Category Gap Matrix

- **QUESTION** → Where is projected target shortfall concentrated?
- **GRAIN** → Month × Region × Channel × Category.
- **HOW TO READ** → Start with Q4/month total; expand Region, Channel,
  Category; separate negative gaps from positive offsets.
- **DRILL PATH** → Month → Region → Channel → Category; compare the exact
  intersection with page trend and forecast.
- **CORRECT INTERPRETATION** → Largest negative intersection contributes to
  gross shortfall; the sum of all signed gaps is the net gap.
- **COMMON MISINTERPRETATION** → Treating gap as a customer target,
  realized loss, or recoverable amount.

### 2. Category → Brand → SKU Product Matrix

- **QUESTION** → Which product groups/SKUs contribute sales, units, ASP,
  discount, or margin signals?
- **GRAIN** → Product/category hierarchy under selected time/customer
  context.
- **HOW TO READ** → Compare Net Sales and Quantity, then ASP, discount and
  margin in the same context.
- **DRILL PATH** → Category → Brand → SKU.
- **CORRECT INTERPRETATION** → Descriptive product contribution and
  commercial metrics.
- **COMMON MISINTERPRETATION** → Inferring causal promotion lift or
  allocating target below Category.

### 3. Customer Contribution

- **QUESTION** → Which outlets contribute to observed Sales?
- **GRAIN** → Customer/Outlet.
- **HOW TO READ** → Sort/rank within the selected period and filter context;
  inspect Net Sales and any displayed margin/contribution fields.
- **DRILL PATH** → Region/Channel context → customer → Page 6 risk/segment.
- **CORRECT INTERPRETATION** → Observed customer contribution.
- **COMMON MISINTERPRETATION** → Reading customer sales as target
  achievement or expected future value.

### 4. Core High Decline Customer Table

- **QUESTION** → Which valuable Core / Maintain customers have a validated
  High relative decline tier?
- **GRAIN** → One Customer action at the September 2026 as-of snapshot.
- **HOW TO READ** → Review segment, decline tier, T12M sales/margin,
  Momentum/Engagement context, and mapped Q4-relevant recent sales.
- **DRILL PATH** → Priority → account context → observed trend; then
  validate with account team.
- **CORRECT INTERPRETATION** → Retention-investigation cohort with
  **$20.177B** T12M exposure across 617 customers.
- **COMMON MISINTERPRETATION** → Treating $20.177B as predicted loss or
  guaranteed recovery.

### 5. Potential Customer Table

- **QUESTION** → Which relative Potential customers meet momentum and
  engagement review thresholds?
- **GRAIN** → One Customer action at the September 2026 as-of snapshot.
- **HOW TO READ** → Read segment and saved scores with T12M base and recent
  mapped sales; validate interest/capacity.
- **DRILL PATH** → Potential cohort → customer → account-team validation.
- **CORRECT INTERPRETATION** → 153 customers have **$3.764B** T12M existing
  sales exposure; Outlet 00955 has **$28.066M**.
- **COMMON MISINTERPRETATION** → Calling T12M exposure incremental sales,
  uplift, or a forecast.

### 6. Inventory Review Table

- **QUESTION** → Which current distributor/product positions warrant a
  normal-policy execution review?
- **GRAIN** → Snapshot Date × Distributor × Product.
- **HOW TO READ** → Select one snapshot; inspect On Hand, In Transit,
  Reorder Point, pressure, freshness and recent demand.
- **DRILL PATH** → Snapshot → Distributor → Product; use Category only for
  safe Q4 relevance.
- **CORRECT INTERPRETATION** → Current exception or analytical screening
  condition. In Transit is shown separately from On Hand.
- **COMMON MISINTERPRETATION** → Summing snapshots, declaring a confirmed
  future stockout, or prescribing a quantity from a coverage proxy.

### 7. Management Action Priority Table

- **QUESTION** → What deterministic review item should be considered first?
- **GRAIN** → Mixed: native target-gap segment, Customer action, or
  Distributor × Product inventory position.
- **HOW TO READ** → Sort by Priority Level/Score; check Action Type,
  Commercial Impact, evidence components, Primary Driver and fixed
  Recommendation Template.
- **DRILL PATH** → Priority row → verify the same entity at its source
  grain/page → assign an owner only after local validation.
- **CORRECT INTERPRETATION** → A weighted review queue. The **1,673** rows
  include 219 Critical, 719 High, 703 Medium, and 32 Low.
- **COMMON MISINTERPRETATION** → Adding mixed-grain action rows together
  as dollars, treating score as probability, or treating templates as
  proven prescriptions.

## Five labels to keep distinct

**Target Gap = WHERE the gap exists**  
**Customer Risk/Potential = WHO deserves investigation**  
**T12M Exposure = HOW MATERIAL the existing business base is**  
**Priority Score = WHAT to review first**  
**Recommendation = WHAT action to consider**

Exposure ≠ expected loss; Potential exposure ≠ incremental sales; recent
gap-area sales ≠ recoverable revenue; inventory pressure ≠ confirmed
stockout.
