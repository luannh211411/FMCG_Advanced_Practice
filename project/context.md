# Project Context

## Scope
FMCG Commercial Analytics analytical foundation. This milestone builds and validates the dimensional analytical model; Power BI and exploratory commercial analysis are explicitly out of scope.

## Available period
- Sales transactions: 2025-01-01 to 2026-09-30
- Targets: 2025-01-01 to 2026-12-01 at monthly grain
- Inventory snapshots: 2025-01-31 to 2026-09-30
- Promotions: date-ranged/category/channel applicability

## Raw and processed assets
- Raw CSV folders: `data/`
- Processed CSV outputs: `processed/`
- Primary analytical database: `database/fmcg_analytics_main.duckdb`
- Legacy/locked database retained: `database/fmcg_analytics.duckdb`
- Existing Python pipeline: `src/`
- Existing SQL: `.venv/SQL/sql/`
- Existing notebook: `01_data_audit.ipynb`

## Governance note
The requested `.github/copilot-instructions.md` and `skills/commercial-analytics/SKILL.md` were not found in this repository. This absence is recorded as a limitation; repository conventions and the user's Commercial Analytics Agent OS are followed directly.

## Evidence gathered
- 620,000 sales rows; TransactionID unique and non-null.
- 24,000 return rows; ReturnID unique, each currently maps to one sales transaction.
- 1,728 target rows at Month + Region + Channel + Category; no duplicate keys.
- 75,600 inventory rows at SnapshotDate + DistributorID + ProductID; no duplicate keys.
- 6,500 customers, 180 products, 120 sales representatives, 60 promotions.
- Sales formula checks passed for all rows: NetSales = GrossSales - DiscountAmount and GrossMargin = NetSales - COGS.
- Sales customer/product and customer sales-rep foreign-key coverage is currently complete.
- The live DuckDB file was locked by VS Code during inspection; CSV-level evidence is complete, and database-level checks must be rerun after controlled database access is available.
