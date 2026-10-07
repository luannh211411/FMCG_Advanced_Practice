# Project Status

## Current milestone
Prescriptive Build 2 — Q4 Target Recovery & Action Priorities (Page 7).

## State
**Page 7 and the Q4 Action Priority semantic integration are implemented. PBIR validation has no structural errors; data-backed DAX evaluation and Desktop rendering remain pending because the Modeling MCP connection is offline and Power BI Desktop is unavailable in this environment.**

## Completed and validated
- Repository and assets inspected, excluding dependency internals under `.venv`.
- Raw and processed CSV counts reconciled.
- Sales: 620,000 rows, unique TransactionID, no nulls, formula checks passed, customer/product FK coverage complete.
- Customer: 6,500 unique CustomerID; all SalesRepID values resolve to 120 sales-force rows.
- Product: 180 unique ProductID.
- SalesForce: 120 unique SalesRepID.
- Returns: 24,000 unique ReturnID; all TransactionID, CustomerID and ProductID references resolve; one return row per transaction in current data.
- Targets: 1,728 unique Month + Region + Channel + Category rows.
- Inventory: 75,600 unique SnapshotDate + DistributorID + ProductID rows; all distributor/product identifiers resolve to available source keys.
- Promotions: 60 unique PromotionID; valid date ranges; 8 overlap events detected within Category + Channel groups.
- Existing notebook cells are not executed; one code cell contains plain text and would fail if run.

## Known gaps
- No repository copies of `.github/copilot-instructions.md` or `skills/commercial-analytics/SKILL.md` were found.
- The legacy `database/fmcg_analytics.duckdb` remains locked by VS Code, so it is retained as an archive and is not the active source.
- The notebook remains unexecuted and contains one invalid plain-text code cell; its findings were independently validated by the pipeline and DuckDB checks.

## Predictive feature engineering
- Added reproducible SQL-driven feature build: `src/build_features.py` and `src/sql/predictive_features.sql`.
- Created `feature_sales_monthly`, `feature_customer_monthly` and `feature_inventory_risk` in the separate `database/fmcg_predictive_features.duckdb`; CSVs and `feature_validation.json` are in `processed/features/`.
- Sales history contains 21 consecutive calendar-complete months (2025-01 through 2026-09), 620,000 transactions. Inventory contains 21 monthly snapshots (2025-01-31 through 2026-09-30).
- Feature key, null, impossible-value and lookback/as-of checks passed. Sales and customer-month Sales totals reconcile exactly to fact Sales; monthly/customer-month returns reconcile exactly through 2026-09-30; inventory measures reconcile per snapshot date.
- 528 returns dated after the latest complete Sales month are excluded from historical features. Customer JoinDate was excluded because 52,842 transactions across 1,292 customers predate it.
- Customer segmentation/risk is completed in Predictive Build 3. Inventory intelligence is being completed in Predictive Build 4; DAX and predictive report visuals remain unstarted.

## Predictive Build 2 — Sales Forecast
- Added reproducible rolling-origin backtest and forecast build in `src/forecast_sales.py`; inputs are the validated Build 1 feature database and analytical target fact, both read-only.
- Evaluated last observed, trailing 3-month average, last-6-month linear trend, 12-month seasonal naive, and fixed-parameter damped Holt.
- Seven time-ordered origins (2025-12 through 2026-06), horizons 1–3; 72/72 series eligible, 1,512 evaluation forecasts per method. Backtest eligibility is evaluated as-of each origin to avoid future leakage.
- Selected the global trailing 3-month average (pooled WAPE 5.6729%, Bias +0.1363%, MAE 12,244,593.81). Seasonal naive is diagnostic only given one annual cycle; damped Holt did not improve on the selected baseline.
- Persisted 216 forecast rows and 216 native-grain target-gap rows for Oct–Dec 2026; all 216 target joins matched, no zero targets or negative forecasts. Outputs and detailed backtest/model comparison tables are in `database/fmcg_predictive_outputs.duckdb` and `processed/predictive/`.
- Forecast models, customer segmentation/risk and Build 4 inventory intelligence are completed as separate predictive builds; DAX, semantic-model changes and predictive report visuals have not been started.

## Predictive Build 3 — Customer segmentation and risk
- Added reproducible scoring and validation builder `src/build_customer_intelligence.py`; it reads the Build 1 customer feature database and writes only Build 3 named tables to the existing predictive output database and CSV folder.
- Created `fact_customer_segment_risk` at CustomerID × AsOfMonth × ModelOrRuleVersion grain: 136,416 rows, 6,500 customers, January 2025–September 2026. All 6,500 customers are scored in the current 2026-09-30 snapshot; 32,500 earlier customer-month rows are retained as insufficient history.
- Created separate relative commercial segments and decline/inactivity score tiers. Segment rules use within-month empirical percentiles, six months minimum history, and require two consecutive candidate months to switch Risk/Potential classifications.
- Decline score uses only as-of history and was direction-oriented on development outcomes; High tier is set at the development-score P80. Forward three-month rolling validation: 25,916 development and 39,000 temporal-holdout observations. Holdout ROC-AUC 0.6914, average precision 0.3824; High-tier event rate 42.30% vs 25.00% overall, 1.69× lift, 32.07% event capture.
- Inactivity had zero positive outcomes in development and holdout (25,916 and 39,000 observations). Its score tiers are provisional relative rankings and are not validated predictive risk.
- September 2026 segments: Potential 213, Core 2,753, Risk/Declining 474, Low Priority/Dormant 3,060. High decline tier: 1,268 customers; provisional High inactivity tier: 1,363; both: 171.
- Segment stability is 78.69% across all 129,916 consecutive transitions and 78.25% across the 97,416 transitions excluding insufficient-history states. ±5-point threshold sensitivities change 9.49% and 11.66% of current assignments.
- Grain, null-key, segment completeness, eligible-score, one-to-one input-key and Net Sales/trailing-12-month Sales reconciliation checks passed. The Build 1 feature database is unchanged, and all five Build 2 forecast/backtest tables match the pre-build snapshot.
- Details, score definitions, thresholds, validation and limitations are in `model/customer_intelligence.md`. No Power BI/model, inventory-risk, or prescriptive changes were made.

## Predictive Build 4 — Inventory risk and coverage intelligence
- Added reproducible builder `src/build_inventory_intelligence.py`; it reads validated inventory features and analytical Sales/inventory facts read-only, and writes only Build 4 outputs.
- Created wide `fact_inventory_risk` at SnapshotDate × DistributorID × ProductID × ModelOrRuleVersion grain: 75,600 rows, 3,600 positions across 21 snapshots from 2025-01-31 through 2026-09-30.
- Current-state flags cover reorder exception, expired quantity, zero On Hand, In Transit, recent demand, and demand-history availability. On-Hand coverage is separate from On-Hand-plus-In-Transit coverage; missing history and zero velocity remain null/not applicable.
- Added analytical coverage-pressure and excess/slow-moving screening scores with documented empirical thresholds; these are relative severity levels, not probabilities or operating service-level thresholds. Current reorder exception and expired inventory are supported current conditions; replenishment pressure and excess/slow-moving are partially supported. Future stockout and future expiry are unsupported.
- As of 2026-09-30: 802 reorder exceptions; 3 zero-On-Hand positions; 3,502 positions with ExpiredQuantity > 0 (52,189 expired units); 998 coverage-pressure positions (307 Medium, 691 High); 905 excess/slow-moving positions (534 Medium, 371 High); zero mature No Recent Demand positions. The high expired-condition prevalence is reported from source without reinterpretation.
- Thresholds calibrated using mature 2025 history: On-Hand coverage P25 93.85 days; low available coverage P25 112.06 days; trend P25/P75 -19.13%/+25.38%; pressure score P75/P90 35/80; excess score P75/P90 40/65. Monthly On-Hand coverage P25 ranged 88.83–98.59 days across 18 mature snapshots.
- All 21 snapshot inventories and reorder flags reconcile exactly to `fact_inventory`; all 75,600 pre-snapshot recent/prior demand windows reconcile to analytical Sales. Formula, freshness, key uniqueness and coverage tests passed. Inventory remains semi-additive; checks and outputs report quantity by snapshot only.
- Across 72,000 transitions, unchanged rates are 66.92% for reorder, 93.71% for expired condition, 62.17% for pressure, 59.52% for pressure level, and 69.66% for excess/slow-moving. Descriptive next-three-month demand comparisons are non-causal; the High excess/slow-moving group had median future/recent demand ratio 1.327 and does not validate a future decline signal.
- Same-date rebuilds reproduce all Build 4 outputs. The Build 1 feature database, analytical database and all 15 pre-existing Build 2/3 output tables are unchanged.
- Documentation is in `model/inventory_intelligence.md`. No Power BI, DAX, semantic-model, lost-sales, future-stockout/expiry, or prescriptive work was done.

## Build results
- Processed outputs now include `dim_date.csv` (730 rows) and `dim_distributor.csv` (20 rows).
- Primary DuckDB `database/fmcg_analytics_main.duckdb` loaded all 10 tables successfully.
- `vw_sales_analysis`: 620,000 rows and unique TransactionID cardinality preserved.
- `vw_returns_analysis`: 24,000 rows.
- `vw_sales_promotion_candidates`: 60,699 candidate matches.
- `vw_sales_promotion_attributed`: 57,570 attributed rows; 3,129 rows flagged with overlap.
- `vw_monthly_sales_target`: 1,512 rows; 0 unmatched target rows.
- `vw_inventory_latest`: 3,600 rows and 3,600 unique DistributorID + ProductID keys.
- `get_errors` reported no diagnostics in edited Python files.
- `src/load_database.py` now defaults to `database/fmcg_analytics_main.duckdb`.
- `fact_promotion_attribution` is materialized from the validated promotion attribution view.
- DuckDB ODBC is unavailable; the Local PBIP will import validated processed CSVs generated from the primary DuckDB pipeline.

## Semantic-model implementation state
- Added shared Month, Region, Channel and Category dimensions to the Local PBIP semantic model.
- Month filters both Date/Sales and Targets; Region and Channel filter Customer/Sales and Targets; Category filters Product/Sales and Targets.
- Removed the invalid direct daily Date-to-monthly Targets relationship.
- The Targets fact remains separate at Month + Region + Channel + Category grain and `Sales Target` remains an explicit native-grain measure.
- Source/target coverage was checked against the authoritative DuckDB data: all target Region, Channel, Category and Month values resolve to the corresponding shared dimensions; 1,728 target-grain keys are unique.
- Power BI Desktop was launched twice for runtime validation. The Desktop Bridge connected at launch, but the model reload returned no success payload and the process exited; a subsequent launch reported `BRIDGE_UNAVAILABLE` (`EPERM` on the Desktop Bridge pipe). Runtime refresh, CSV conversion and engine-level relationship validation therefore remain inconclusive and must be rerun from a healthy Desktop Bridge session.
- Added Average Sales per Active Customer, Previous Month Sales, MoM Variance, MoM Growth %, Previous Year Sales, YoY Variance, YoY Growth %, and Weighted Discount %.
- DuckDB reconciliation confirms total net sales of 327,109,162,314, gross margin of 120,055,809,705 (36.70%), weighted discount of 7.69%, return amount of 3,899,954,255 (1.19% of net sales), and latest on-hand inventory of 1,428,342 units. Target achievement reconciles to 75.93% and variance to -103,690,786,966 at the target grain.

## Report implementation state
- Preserved the existing report pages 1–5 and semantic model; Page 6, "Commercial Outlook & Outlet Risk", was added to the existing PBIR report.
- Executive KPI strip now includes Net Sales, Sales Target, Target Achievement %, Gross Margin %, MoM Growth %, and Active Customers.
- Target & Performance Drivers has Year, Month, Region, Channel and Category slicers using the correct conformed fields.
- Growth Opportunities has Year, Region and Channel slicers plus category, customer and channel-comparison visuals and an expanded opportunity table.
- Execution & Exceptions has Snapshot Date, Distributor and Region slicers; promotion overlap remains exposed through its existing KPI.
- Diagnosed the report-rendering blocker: 11 dropdown slicers stored their formatting `objects` under `visual.query` rather than alongside `query` under `visual`, contrary to the PBIR visual-container schema.
- Repaired those 11 slicers in place and set their 56px heights to the validator's 76px dropdown minimum; the increased bounds were checked for collisions and page overflow.
- The report was not rebuilt and the semantic model was not modified. Existing pages 1–5 remain in the page order, Page 6 is appended, and the original Page 5 remains active.
- Page 6 includes the approved forecast-versus-target, outlet portfolio, validated decline-risk, and latest-snapshot inventory-pressure views. As-of/snapshot and Q4 forecast filters remain separate; no predictive DAX or semantic-model edits were made.
- `powerbi-report-author validate` succeeds with 0 errors; one warning remains because the CLI cannot fetch the external visual-container schema. Power BI Desktop opened the PBIP and rendered Page 6 successfully. The forecast currency cards display in billions, percentage cards remain percentages, and the inventory table fits without horizontal scrolling.
- A complete pre-repair copy of `FMCG Commercial Review.Report` is retained in the current Copilot session's files.

## Next milestone
Prescriptive Build 2 is complete. Await approval before further prescriptive work; do not begin Executive Takeaways or final QA.

## Report planning state
- Audience: Commercial / Sales Managers.
- Purpose: performance tracking, growth opportunities, execution monitoring and recurring business review.
- Delivery: Local PBIP.
- Composition: Commercial Review 6 pages, including Page 6 "Commercial Outlook & Outlet Risk".
- Design identity: Corporate Cool.

## Predictive Integration — Semantic Model & DAX
- Added `Sales Forecast` (216 rows; Forecast Month × Region × Channel × Category × Model Version × Run Date), `Customer Intelligence` (136,416 rows; Customer × As Of Month × Model/Rule Version), `Inventory Intelligence` (75,600 rows; Snapshot Date × Distributor × Product × Model/Rule Version), and a disconnected 20-row `Forecast Backtest Summary` utility table.
- Added nine active, single-direction relationships to shared Month, Region, Channel, Category, Customer, Date, Product and Distributor dimensions. No fact-to-fact relationships were added; targets remain at Month × Region × Channel × Category and use the existing `Sales Target` measure.
- Added 26 measures: forecast/target gap and attainment, pooled historical forecast WAPE/Bias, latest-as-of customer segment and decline/inactivity signal counts, and latest-snapshot inventory values and screening-position counts. Inactivity remains provisional and separate from validated decline risk; inventory remains semi-additive and In Transit is separate from On Hand.
- M partitions import existing CSV outputs under `processed/predictive/`; upstream feature, forecast, customer and inventory outputs were not rebuilt or modified.
- Source checks: all 216 forecast rows match a target at native grain with no zero/missing targets or negative forecast values; customer-month and inventory snapshot keys are unique; customer, product, distributor and available month/date keys resolve to the authoritative analytical dimensions. The latest customer snapshot contains 6,500 customers; inventory output contains 21 monthly snapshots through 2026-09-30.
- The selected forecast's pooled historical backtest metrics remain sourced from the validated comparison output: WAPE 5.6729%, Bias +0.1363%, seven rolling-origin cutoffs and 1,512 evaluated forecasts.
- MCP metadata confirms 26 tables, 68 measures and 37 relationships. All 26 new measures were retrieved without metadata errors and report `Ready`; however, the four new partitions remain `NoData`, relationships remain `CalculationNeeded`, and DAX query validation is unsupported on this offline connection. No runtime refresh or data-backed DAX result is claimed.
- During semantic-model integration, pages 1–5 were not changed. The semantic model was exported to its existing `definition` folder; the pre-change TMDL snapshot remains in the session files folder.
- Report spec: `_brief/report-spec.md`.
- Spec acceptance checks: passed — design marker, contract version, 4 pages, 4 layout contracts, 4 page titles, no unplaced regions, no placeholders.
- Current gate: semantic-model runtime refresh and data-backed DAX validation remain pending; Page 6 report rendering is confirmed.

## Prescriptive Build 1 — Q4 Target Recovery Priority Engine
- Added reproducible builder `src/build_q4_action_priority.py`, using existing validated forecast, customer-intelligence, inventory-risk and analytical outputs read-only.
- Created `fact_q4_action_priority` (1,673 unique actions) plus component/threshold configuration, gap concentration, customer/inventory summary, sensitivity and validation outputs in `database/fmcg_predictive_outputs.duckdb` and `processed/prescriptive/`.
- The Q4 benchmark is Forecast Sales 46.504B vs Target 48.841B, net gap -2.337B. Scoring weights are Commercial Impact 30%, Risk/Opportunity Severity 25%, Q4 Relevance 20%, Evidence Confidence 15%, and Actionability 10%; bands: Critical ≥80, High ≥65, Medium ≥45, Low <45.
- Customer protection includes 617 Core / Maintain + validated High Decline Risk customers; 153 Potential customers meet the existing momentum/engagement qualification. Inventory review includes 741 demand-supported Medium/High-pressure or reorder positions from the 2026-09-30 snapshot.
- Inventory relevance is joined only at Product Category because each distributor maps to 12 Region × Channel combinations. No causal, revenue recovery, lost-sales, exact stock-quantity, or provisional-inactivity action claims are made.
- Build validation: forecast-target gap formula reconciles within one cent; forecast and source snapshot keys are unique; action IDs are unique; output scores and deterministic action templates validate. No PBIR/report or semantic-model files were changed.
- Details and limitations: `model/q4_target_recovery_priority.md`. Await approval before starting another prescriptive milestone.

## Prescriptive Build 2 — Semantic Integration + Page 7
- Added the imported `Q4 Action Priority` table (1,673 rows) from the validated Build 1 CSV, deriving `Primary Driver` and `Evidence Type` deterministically in its M partition. Added only single-direction relationships to Customer and Category; no Month, Region, Channel, Distributor or Product action-fact relationships were added.
- Added explicit Q4 KPI, gross-negative-gap concentration, deduplicated customer-exposure, inventory-count, and management-focus measures. Exported the updated semantic model to the existing TMDL definition folder.
- Added exactly one page, `Q4 Target Recovery & Action Priorities`, with Q4 outlook, ranked native-grain gap review, Critical/High customer and Potential views, Category-mapped inventory review, and a Top 15 deterministic management-focus table. Pages 1–6 and the active-page selection are unchanged.
- Source reconciliation: Q4 forecast 46.503894B, target 48.840684B, net gap -2.336789B, achievement 95.2155%; the top five Region × Channel × Category gross-negative-gap combinations contribute 28.7988%. Action count/distribution, 617 Core/High-decline customers, 153 Potential customers, and 741 inventory positions reconcile to Build 1.
- The Build 1 customer summary defines Potential Jul–Sep sales as 1.416B total, of which 0.465B maps to negative-gap intersections. Page 7 labels total recent sales and mapped recent sales separately; no upstream output was changed.
- `powerbi-report-author validate` succeeds with 0 errors; the remaining warning is inability to fetch the external visual-container schema. DAX query evaluation is unsupported on the offline MCP connection, and Desktop Bridge reports no connected instance; opening the PBIP also reports no Desktop executable. Rendering and data-backed measure results are therefore not claimed.
