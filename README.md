# Advanced FMCG Analytics Practice Dataset

Period: Jan-2025 to Sep-2026 sales; targets extend through Dec-2026.
Scale: ~620k sales transactions + inventory snapshots + returns + dimensions.

Recommended model:
- FactSales: monthly files in data/sales/sales_YYYY-MM.csv
- FactReturns: data/sales/sales_returns.csv
- FactTarget: data/targets/fact_target.csv
- FactInventorySnapshot: data/inventory/fact_inventory_snapshot.csv
- DimCustomer, DimProduct, DimSalesforce, DimPromotion
- Build a proper DimDate yourself.

Important modeling challenges:
1. Targets have a different grain from sales.
2. Inventory is a periodic snapshot fact.
3. Returns reference original sales transactions.
4. Promotions are date-range/category/channel based, not a simple ProductID key.
5. Customer contains geography/channel/distributor/sales rep attributes.
6. Practice weighted discount, gross margin, active customers, return rate, target achievement,
   inventory health, sales rep productivity, MoM/YoY and contribution analysis.
7. The data contains deliberately planted commercial patterns for you to discover.

Suggested pipeline:
Raw folders -> Python ingestion/validation -> processed fact/dimension tables -> Power BI PBIP/Agentic.
