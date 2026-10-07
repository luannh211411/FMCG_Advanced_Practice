# Modeling Decisions

## Confirmed
1. Keep a star-schema analytical layer; do not create one denormalized mega-table.
2. FactSales grain is one transaction (`TransactionID`).
3. FactReturns remains a separate fact at one return row (`ReturnID`) and retains `TransactionID` as a degenerate/original-sale reference.
4. FactTarget remains separate at Month + Region + Channel + Category; it must not be joined directly to transaction rows.
5. FactInventorySnapshot remains a periodic snapshot at SnapshotDate + DistributorID + ProductID and is semi-additive across time.
6. Product, Customer and SalesForce remain conformed dimensions for sales analysis.
7. A proper DimDate is required and must cover the sales, return, inventory and target reporting horizons.
8. Promotion matching must use date range + category + channel. Because 8 overlap events exist within category/channel groups, attribution must be deterministic or exposed as a bridge with overlap diagnostics.
9. Predictive Sales Forecast relates to shared Month, Region, Channel and Category dimensions at the native target grain; it must not relate directly to Targets.
10. Customer Intelligence is an as-of fact related through shared Customer and Month dimensions. Inactivity tiers remain provisional and separate from validated decline risk.
11. Inventory Intelligence relates through shared Date, Product and Distributor dimensions. Quantity measures use the latest selected snapshot; On Hand and In Transit remain separate.
12. Forecast Backtest Summary is a disconnected audit utility. Backtest WAPE/Bias measures read its validated comparison output and are not future forecast accuracy.

## Planned structural changes
- Add and load `dim_date`.
- Add a derived `dim_distributor` from distinct distributor identifiers because distributor analysis is supported by source keys but no standalone dimension exists.
- Add explicit relationship/quality validation scripts and database views that preserve native fact grains.
- Add a promotion applicability/attribution layer using the deterministic rule: highest PromoDiscountPct, then latest StartDate, then lowest PromotionID. Preserve MatchingPromotionCount and HasPromotionOverlap for transparency.

## Implemented in this milestone
- `database/fmcg_analytics_main.duckdb` is now the primary analytical database; the locked legacy file remains unchanged as an archive.
- `src/pipeline.py` creates and validates `dim_date` and `dim_distributor`.
- `src/validate.py` checks model keys, foreign-key coverage, formula integrity, date coverage, promotion ranges and fact-row multiplication.
- `src/load_database.py` loads the new dimensions and executes `04_model_views.sql`; `FMCG_DB_PATH` supports isolated validation builds.
- `04_model_views.sql` provides relationship-safe sales, returns, promotion candidate/attribution, monthly target and latest inventory views.
- DuckDB ODBC is not installed on this Windows environment. Local PBIP Import partitions will use the validated `processed/*.csv` outputs; the primary DuckDB remains the authoritative transformation/validation source. Promotion attribution is materialized as `fact_promotion_attribution` for stable semantic-model import.
- The Local PBIP semantic model uses CSV imports for simplicity, portability and reliable local refresh without an additional DuckDB ODBC dependency. DuckDB remains the authoritative transformation and validation source; processed CSVs are the Power BI import contract.
- Targets are filtered through shared semantic Month, Region, Channel and Category dimensions rather than by a direct relationship to transaction-level Sales. This preserves the target fact's native Month + Region + Channel + Category grain and prevents target multiplication.
- The semantic Month dimension filters both Date and Targets. The direct daily Date-to-monthly Targets relationship is intentionally removed because it does not represent the monthly target grain correctly.
- `Sales Target` additionally transfers the Date Month Start, Customer Region/Channel and Product Category context to Targets with `TREATAS`. This keeps existing report bindings correct while the shared dimensions remain the preferred target-analysis fields.
- The Sales measure layer includes only justified additional measures: Average Sales per Active Customer, previous-period sales, MoM/YoY variance and growth, and Weighted Discount %. All use explicit aggregation and `DIVIDE` for safe ratios.
- Predictive Integration added four import tables (three predictive facts plus the disconnected backtest summary), nine single-direction shared-dimension relationships and 26 explicit measures. No existing Diagnostic measure or report page was changed.
- Customer snapshot measures use the latest As Of Month in context. Inventory measures use the latest Snapshot Date in context, preserving semi-additive quantities and distinguishing On Hand from In Transit.
- The semantic model imports the validated predictive CSV outputs from `processed/predictive/`; Build 1–4 output databases and CSVs remain read-only inputs.

## Prescriptive Build 2 — Q4 Action Priority
- `Q4 Action Priority` is a mixed-grain action fact. It relates single-direction to Customer for customer actions and Category for native commercial-gap/category inventory context only.
- Do not relate the action fact directly to Month, Region, Channel, Distributor or Product. Inventory geography is not validated below Category; mixed-grain action filtering must not imply otherwise.
- Keep Build 1 action scoring, thresholds and output immutable. Customer revenue values are historical exposure, Potential is a validation cohort, inventory pressure is screening rather than stockout prediction, and Q4 gaps remain forecast benchmarks rather than guaranteed results.
- Keep Q4 KPI measures on the existing forecast/target measures at the native Month × Region × Channel × Category grain. Gross-negative-gap contribution uses gross negative shortfall, not the net company gap.
- Distinguish Potential Jul–Sep total sales (1.416B) from sales mapped to negative-gap intersections (0.465B), as reported by the validated Build 1 output; do not relabel total sales as mapped sales.
- Page 7 defaults its management tables to Critical/High and a bounded Top-N view. Region/Channel/Category are not global slicers across all action types; inventory linkage remains category-level only.

## Not yet decided
- Historical slowly changing treatment for customer sales-rep/distributor assignments is not possible from current source data.
- Preferred inventory aggregation convention requires business confirmation.
