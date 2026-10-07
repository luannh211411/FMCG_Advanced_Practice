# Q4 Target Recovery Priority Engine — Prescriptive Build 1

## Scope and guardrails

This deterministic priority queue organizes review work against the approved
Q4 2026 forecast-target gap. It is not causal, does not estimate recoverable
revenue or lost sales, and does not prescribe inventory quantities. Inputs
are read-only validated forecast, customer-intelligence and inventory-risk
outputs, plus source customer/product mappings and Jul–Sep 2026 sales.

- As of: **2026-09-30**; run date: **2026-10-07**
- Rule version: `fmcg-q4-action-priority-v1.0.0`
- Rebuild: `.venv\Scripts\python.exe src\build_q4_action_priority.py --run-date YYYY-MM-DD`
- Output: `database/fmcg_predictive_outputs.duckdb` and
  `processed/prescriptive/`

No PBIR, report, semantic-model, source-fact, or upstream predictive feature
tables were changed.

## Q4 Target Recovery framework

The unit of target-gap action is the native
`ForecastMonth × Region × Channel × Category` grain. A gap action is emitted
only for a negative forecast-target gap. Customer and inventory actions are
separate entity-level review items and are not additive to the gap amount.

| Q4 2026 | Forecast Sales | Sales Target | Net Gap | Gap % |
|---|---:|---:|---:|---:|
| October | 15.501B | 15.946B | -0.445B | -2.79% |
| November | 15.501B | 16.087B | -0.586B | -3.64% |
| December | 15.501B | 16.808B | -1.306B | -7.77% |
| **Q4 total** | **46.504B** | **48.841B** | **-2.337B** | **-4.78%** |

Across the 216 month/region/channel/category rows, 162 have a negative gap
(gross shortfall **19.760B**) and 54 have a positive gap (offset **17.423B**).
These positive intersections explain why the net Q4 gap is smaller than the
sum of negative intersections; positive gaps are not treated as recoveries.

Largest Q4 negative-gap concentrations by Region × Channel × Category:

| Intersection | Q4 negative gap | Share of gross shortfall |
|---|---:|---:|
| South × GT × Beverages | -1.339B | 6.78% |
| South × GT × Snacks | -1.233B | 6.24% |
| North × GT × Beverages | -1.141B | 5.77% |
| North × GT × Snacks | -0.999B | 5.06% |
| South × MT × Beverages | -0.978B | 4.95% |

The five intersections account for about **28.8%** of the gross negative
shortfall.

## Priority score and thresholds

Each score component is on a 0–100 scale. The weighted score is the sum of
component score × weight.

| Component | Weight |
|---|---:|
| Commercial Impact | 30% |
| Risk / Opportunity Severity | 25% |
| Q4 Relevance | 20% |
| Evidence Confidence | 15% |
| Actionability | 10% |

Commercial-impact percentiles are computed within the applicable action
cohort: absolute negative gap, customer trailing-12-month sales within each
customer action group, or recent three-month units within eligible inventory
positions. This normalizes unlike units for ranking; component scores are not
monetary values.

| Priority | Score |
|---|---:|
| Critical | ≥80 |
| High | ≥65 and <80 |
| Medium | ≥45 and <65 |
| Low | <45 |

### Component evidence and scoring

- **Gap actions:** commercial impact is the within-gap-cohort percentile of
  absolute shortfall; severity is absolute gap percentage, capped at 100;
  Q4 relevance is 100.
- **Customer protection:** impact is trailing-12-month sales percentile.
  Validated High decline risk receives severity 100. Customer Q4 relevance is
  the share of Jul–Sep net sales in that customer's current Region × Channel ×
  Category intersections with at least one negative Q4 gap.
- **Potential growth validation:** only Potential customers with
  MomentumScore ≥70, EngagementScore ≥50, and positive trailing-12-month sales
  qualify. Severity is the mean of the as-of momentum and engagement scores.
  No future uplift or incremental revenue is calculated.
- **Inventory review:** impact is recent three-complete-month sales-quantity
  percentile; severity is the greater of the coverage-pressure score and 65
  for a current reorder exception. Product Category is the only Q4 mapping
  level: every distributor spans all 12 Region × Channel combinations, so
  assigning a distributor position to a particular Q4 geography would be
  unsafe. Category relevance is 60–100 based on relative category gross
  shortfall.

Evidence-confidence anchors are 72 for forecast-gap actions (short history and
seven rolling origins), 80 for validated but non-calibrated High decline-risk
actions, 65 for relative Potential signals, 85 for current reorder exceptions,
and 70 for coverage-pressure screening. Actionability anchors are 90 for
native-grain gap review, 75 for account-team review, and 80 for normal-policy
inventory review. These are transparent prioritization judgments, not
statistical confidence intervals.

## Customer and inventory priority rules

### Customer revenue protection and opportunity

- Protection rule: `CORE / MAINTAIN` **and** the validated `High`
  `DeclineRiskLevel`, at the 2026-09 customer snapshot. Provisional
  inactivity is not used.
- **617** qualifying customers: trailing-12-month sales **20.177B**, gross
  margin **7.397B**; Jul–Sep sales **6.716B**, of which **1.919B** is in
  exact current-customer-geography/category intersections with a negative Q4
  gap. These are observed exposure amounts, not sales at risk or recoverable
  value.
- Opportunity rule: Potential plus the existing momentum/engagement
  qualification and positive trailing sales.
- **153** qualifying customers: trailing-12-month sales **3.764B**, gross
  margin **1.367B**; Jul–Sep sales **1.416B**, of which **0.465B** lies in
  mapped negative-gap intersections. These figures describe existing
  commercial value/exposure, not projected growth.

Customer historical sales are attributed using the current customer
Region/Channel assignment because assignment history is unavailable.
Product category is observed from transaction product keys.

### Inventory execution relevance

Include only the 2026-09-30 snapshot positions with observable demand history,
positive trailing-three-complete-month sales quantity, and either Medium/High
coverage pressure or a current reorder exception. This yields **741**
positions: **525 High**, **216 Medium**, **602** with a reorder exception,
and **148,691 units** of trailing-three-month demand. The snapshot freshness
field is at most **6 days** for these rows.

Reorder exception is labeled a **current execution exception**. Coverage
pressure is a screening feature, not a stockout prediction. Neither is used
to prescribe a quantity. Expired quantity is retained as context but is not an
independent action trigger here. Inventory-to-Q4 relevance is category-only;
there is no asserted distributor-to-region/channel match.

## Deterministic actions and recommendation templates

| Action type | Rule | Recommendation template intent |
|---|---|---|
| `Q4_GAP_REVIEW` | Negative native-grain Q4 gap | Review local drivers and assign owner / next review. |
| `CORE_HIGH_DECLINE_REVIEW` | Core / Maintain + validated High decline | Review observed trend and account context; confirm retention needs. |
| `POTENTIAL_GROWTH_VALIDATION` | Qualified Potential customer | Validate momentum, engagement, interest, and capacity before recording an opportunity. |
| `INVENTORY_COVERAGE_PRESSURE_REVIEW` | Eligible Medium/High pressure or reorder position | Review On Hand, reorder point, recent demand, and inbound status under normal policy. |

Templates are fixed strings generated by action type. No free-form model
recommendations, causal claims, revenue-recovery estimates, lost-sales
estimates, or exact stock quantities are generated.

## Queue results and sensitivity

The queue contains **1,673** unique actions:

| Priority | Actions |
|---|---:|
| Critical | 219 |
| High | 719 |
| Medium | 703 |
| Low | 32 |

Weight sensitivity changes one component by ±5 percentage points and
proportionally renormalizes the other weights; priority thresholds stay fixed.
Across ten scenarios, top-100 overlap with the baseline is **88–99%**,
Spearman rank correlation is **0.9849–0.9998**, and **54–160** rows (3.2–9.6%
of the queue) change priority band. Q4 Relevance weight changes cause the
largest top-100 membership movement. This is a weight robustness check, not
outcome validation.

## Validation and persisted outputs

- 216 Q4 forecast-target rows, 216 unique native-grain keys, all three months
  present, no null/zero targets. Stored gap reconciles to ForecastSales minus
  SalesTarget within one cent.
- Inputs include the 6,500-customer September snapshot and 3,600-position
  September inventory snapshot; customer and inventory keys are unique.
- 1,673 action IDs are unique; action identity fields are complete; scores
  stay within 0–100; deterministic templates are populated.
- No inactivity trigger, recovery/lost-sales estimate, or exact inventory
  quantity instruction is present.
- Output database tables and CSV audit copies are created only for Build 1:
  `fact_q4_action_priority`, `q4_gap_concentration`,
  `q4_priority_component_config`, `q4_priority_threshold_config`,
  `q4_priority_weight_sensitivity`, `q4_customer_priority_summary`, and
  `q4_inventory_relevance_summary`. `q4_gap_by_month.csv` and
  `q4_priority_validation.json` provide additional audit detail.

## Limitations

- Forecasting is a benchmark based on 21 complete sales months, seven
  rolling-origin windows, and one global trailing-three-month-average method;
  forecast error is not a certainty measure.
- Customer decline tiers are useful relative rankings for the defined
  outcome, not calibrated probabilities; Potential is a relative
  segment/qualification, not a growth forecast.
- Customer Region/Channel uses current dimension assignments, not a
  historized mapping.
- Distributor mapping spans all 12 Region × Channel combinations; inventory
  relevance is therefore Category-only.
- Inventory lead time, replenishment cadence, and lot/batch expiry inputs are
  absent. Future stockout/expiry is unsupported.
- Priority weights, confidence anchors, actionability anchors and cutoffs are
  transparent governance settings and have not been calibrated to realized
  action outcomes.
