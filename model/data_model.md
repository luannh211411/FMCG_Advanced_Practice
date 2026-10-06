# Target Analytical Data Model

## Existing architecture
The repository already has separate processed CSVs and a DuckDB database containing:
- FactSales
- FactReturns
- FactTarget
- FactInventorySnapshot (currently named `fact_inventory`)
- DimCustomer
- DimProduct
- DimSalesForce
- DimPromotion

The existing pipeline validates only basic sales rules and copies other source tables. Existing SQL assumes a DimDate but does not create/load one.

## Target architecture

```text
DimDate ───────────────┬── FactSales ──── DimCustomer ─── DimSalesForce
                       │       │              │
                       │       │              └── DimDistributor
                       │       └──────────── DimProduct
                       │
                       ├── FactReturns (ReturnDate role; OriginalSaleDate via FactSales reference)
                       ├── FactTarget (Month + Region + Channel + Category)
                       └── FactInventorySnapshot (SnapshotDate + DistributorID + ProductID)

DimPromotion ── PromotionApplicability / PromotionAttribution
                   (date range + category + channel; overlap rule required)
```

## Facts and grain

| Table | Grain | Business key | Main relationships |
|---|---|---|---|
| FactSales | One sales transaction | TransactionID | Date, Customer, Product |
| FactReturns | One return record | ReturnID | ReturnDate, original TransactionID, Customer, Product |
| FactTarget | One monthly target slice | Month + Region + Channel + Category | Date/Month and conformed target dimensions |
| FactInventorySnapshot | One distributor-product snapshot on one date | SnapshotDate + DistributorID + ProductID | Date, Distributor, Product |
| PromotionApplicability | One sale-promotion match candidate | TransactionID + PromotionID | Sales transaction and promotion |
| PromotionAttribution | At most one selected promotion per sale under a deterministic rule | TransactionID | Sales transaction and promotion |

## Dimensions

- DimDate: one row per calendar date, covering at least 2025-01-01 through 2026-12-31.
- DimCustomer: one row per CustomerID; contains geography, channel, distributor and sales-rep attributes.
- DimProduct: one row per ProductID.
- DimSalesForce: one row per SalesRepID.
- DimDistributor: one row per distinct DistributorID derived from trusted customer/inventory identifiers; no descriptive distributor source is currently available.
- DimPromotion: one row per PromotionID and its applicability attributes.

## Why changes are required
1. DimDate is required for valid date joins and target/month alignment.
2. DimDistributor prevents repeated distributor attributes and provides a conformed filter for Customer and Inventory.
3. Separate target and inventory facts prevent target multiplication and invalid summation of snapshots.
4. Separate returns prevents double subtraction and supports both return-date and original-sale analysis.
5. Promotion matching cannot use a simple foreign key because source applicability is conditional and overlaps exist.
6. Native-grain views should be used instead of joining all facts into one table.

## Relationship/cardinality rules
- Every dimension business key must be unique and non-null.
- FactSales to each conformed dimension is many-to-one; joins must preserve 620,000 rows.
- FactReturns to FactSales by TransactionID is many-to-one in the general model; current data is 1:1 but this must not be assumed permanently.
- FactTarget must be joined only after sales aggregation to Month + Region + Channel + Category.
- FactInventorySnapshot is many-to-one to DimDate, DimDistributor and DimProduct; time is semi-additive.
- PromotionApplicability may be one-to-many per sale; it must never be joined to sales for additive measures without attribution or deduplication.
