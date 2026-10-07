# Metric Definitions

## Sales
- Gross Sales: SUM(FactSales.GrossSales)
- Discount Amount: SUM(FactSales.DiscountAmount)
- Net Sales: SUM(FactSales.NetSales)
- COGS: SUM(FactSales.COGS)
- Gross Margin: SUM(FactSales.GrossMargin)
- Quantity: SUM(FactSales.Qty)
- Transaction Count: COUNTROWS(FactSales), with TransactionID unique at fact grain
- Active Customers: DISTINCTCOUNT(FactSales.CustomerID)

## Returns
- Return Amount: SUM(FactReturns.ReturnAmount)
- Return Quantity: SUM(FactReturns.ReturnQty)
- Return Rate: return metric divided by the explicitly selected sales denominator; never subtract ReturnAmount from sales twice through a many-to-many join.

## Targets
- Sales Target: SUM(FactTarget.SalesTarget) only at its native Month + Region + Channel + Category grain.
- Target Achievement: Net Sales / Sales Target after aligning sales to the same month, region, channel and product category.

## Inventory
- On Hand Quantity, In Transit Quantity and Expired Quantity are snapshot measures.
- Latest snapshot and point-in-time measures are valid; summing OnHandQty across dates is not valid without an explicit business definition.

## Promotions
- Promotion applicability is based on transaction date, product category and customer channel.
- Attributed promotion metrics require a documented overlap rule; no promotion attribution is considered validated until that rule is implemented and tested.
