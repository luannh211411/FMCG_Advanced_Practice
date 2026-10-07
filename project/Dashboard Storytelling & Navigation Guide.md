# Dashboard Storytelling & Navigation Guide

## Overall story

**WHAT → WHY → WHERE → WHO → OUTLOOK → ACTION**

Start with business performance, trace drivers, locate the target gap, see
which customers and products contribute, compare the forward benchmark, and
then use the bounded action queue to decide what merits review.

## Grain rules before drilling

- **Target / forecast:** Month × Region × Channel × Category. Compare these
  facts only after alignment to that native grain.
- **Customer:** Customer/Outlet; use customer-level evidence and exposure.
- **Inventory:** Distributor × Product × Snapshot Date; quantities are
  semi-additive and must not be summed across dates.
- Never interpret Target Gap at Customer/Outlet level. A customer can be
  related to an area for investigation, but targets are not allocated to
  customer grain.

## Page 1 — WHAT happened?

- **Business question:** What is the overall commercial position?
- **Look first:** Executive KPI strip—Net Sales, Sales Target, Target
  Achievement, Gross Margin %, MoM Growth %, and Active Customers.
- **Main visuals:** KPI cards establish scale and direction; the summary
  trend/bar visuals provide a first time or performance comparison.
- **Read/drill:** Check net sales and achievement, then margin and growth;
  use the page's time context before drawing conclusions.
- **Move on when:** A material variance needs localization → Page 2. A
  product/customer driver needs explanation → Pages 3–4. Forward outlook or
  action is needed → Pages 6–7.
- **Caution:** The page is a summary. A total can mask offsetting
  Region × Channel × Category results; customer counts are distinct
  customers, not transactions.

## Page 2 — WHERE is the target/growth gap?

- **Business question:** Which native target intersections are below or
  above target, and how does the pattern change over time?
- **Look first:** Target Achievement and Variance by month, then the
  Region → Channel → Category target/growth matrix and trend visuals.
- **Main visuals:** Matrix cells locate value/variance at the target grain;
  trend and comparison charts show timing and relative contribution.
- **Read/drill:** Start at time period, expand Region → Channel → Category,
  and distinguish negative gaps from positive offsets.
- **Move on when:** Product drivers matter → Page 3; customer contribution
  matters → Page 4; expected Q4 trajectory → Page 6; action ranking →
  Page 7.
- **Caution:** Target Gap belongs to Month × Region × Channel × Category.
  It is not a customer-level target and should not be summed after joining
  to transaction-level Sales.

## Page 3 — WHAT product/volume/ASP/discount/margin signals matter?

- **Business question:** Which products and pricing/volume signals explain
  commercial performance?
- **Look first:** Category → Brand → SKU product matrix, then quantity,
  Average Selling Price, discount, and gross-margin comparisons.
- **Main visuals:** Product matrix supports hierarchical contribution
  reading; bar/scatter visuals reveal product-level volume/value and
  price/margin patterns.
- **Read/drill:** Category → Brand → SKU; compare Net Sales and Quantity
  with ASP, Weighted Discount %, and Gross Margin % in the same filter
  context.
- **Move on when:** A region/channel target gap needs review → Page 2;
  a customer contribution needs review → Page 4.
- **Caution:** ASP is aggregate Net Sales divided by aggregate Quantity,
  not an unweighted average of SKU prices. Association between discount,
  price, and sales does not establish causal lift.

## Page 4 — WHO contributes to performance?

- **Business question:** Which customers, channels, and field portfolios
  contribute most to sales or change?
- **Look first:** Customer Contribution matrix and the ranked sales/
  contribution charts.
- **Main visuals:** Customer-level matrix provides account detail; bar
  visuals compare customer, channel, or field contribution under selected
  filters.
- **Read/drill:** Start with the selected channel/region/time context,
  inspect contribution at Customer/Outlet, then move to Page 6 for segment
  and decline context.
- **Move on when:** The question becomes who merits predictive-risk review
  → Page 6; target-area gap → Page 2; action queue → Page 7.
- **Caution:** Contribution describes observed Sales, not account
  profitability unless margin is explicitly shown. Customer geography
  reflects the available customer mapping.

## Page 5 — WHAT execution conditions need investigation?

- **Business question:** What return, inventory, and promotion conditions
  require operational follow-up?
- **Look first:** Snapshot/date filters and current exception counts, then
  the returns, inventory, and promotion matrices/tables.
- **Main visuals:** Time trends and bars compare supported observations;
  inventory tables expose distributor/product snapshot positions and
  returns/promotion visuals provide descriptive context.
- **Read/drill:** Select the relevant period or snapshot; inspect the
  exception at its fact grain; verify the underlying transaction/product/
  distributor context.
- **Move on when:** Forward demand/coverage screening is required → Page 6;
  Q4 action priority is required → Page 7.
- **Caution:** Inventory is a point-in-time snapshot and semi-additive.
  Returns are a separate fact. Promotion attribution is descriptive and
  is not causal lift.

## Page 6 — WHAT is likely to happen?

- **Business question:** What does the selected forecast benchmark imply
  for Q4 target achievement, and which customer/inventory screening signals
  deserve attention?
- **Look first:** Forecast vs Target by October–December, then forecast
  method/as-of context; proceed to customer segment/decline and current
  inventory coverage views.
- **Main visuals:** Forecast-target matrix and trend show the projected
  gap; customer tables show as-of segment/risk evidence; inventory table
  shows current snapshot and supported screening.
- **Read/drill:** Read month and native target intersections first, then
  examine customer-level indicators or inventory at
  Distributor × Product × Snapshot Date.
- **Move on when:** Management must rank deterministic review work → Page 7.
- **Caution:** The selected trailing-three-month average is a benchmark
  based on 21 months and seven rolling origins. WAPE/Bias are historical
  validation, not guaranteed future performance. Decline tiers are relative,
  not calibrated probabilities; inactivity remains provisional. Coverage
  pressure is not stockout prediction.

## Page 7 — WHERE should management act first?

- **Business question:** Which validated gap, customer, or inventory review
  items should be examined first?
- **Look first:** Q4 outlook/gross-gap concentration, then the Core
  customer-protection, Potential-validation, and inventory-review evidence;
  finish with the Critical/High Management Action Priority table.
- **Main visuals:** Q4 KPI cards summarize the benchmark; the
  Region × Channel × Category matrix locates gap concentration; customer
  and inventory tables show entity-level evidence; the priority table ranks
  deterministic actions with Primary Driver and Recommendation Template.
- **Read/drill:** Q4 gap row at Month × Region × Channel × Category →
  customer or inventory evidence at its own grain → Priority Level and
  Action Type → read the template and assign an owner for validation.
- **Move on when:** The action needs sales/product/customer detail → Pages
  2–6. Return to the relevant native-grain view before treating an action
  as operationally confirmed.
- **Caution:** The action table is mixed-grain. Priority Score is a
  normalized weighted review ranking, not money, probability, predicted
  loss, or recovery. Customer and inventory evidence is not additive to
  the target-gap amount. Inventory relevance is Category-only.

## Key interpretation chain

**Target Gap = WHERE the gap exists**  
**Customer Risk / Potential = WHO deserves investigation**  
**T12M Exposure = HOW MATERIAL the existing business base is**  
**Priority Score = WHAT to review first**  
**Recommendation Template = WHAT action to consider**

Exposure does not mean guaranteed loss; Potential exposure does not mean
incremental sales; recent gap-area sales do not mean recoverable revenue;
inventory pressure does not mean confirmed stockout.
