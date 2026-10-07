# FMCG Commercial Review Report Spec

## Report identity
- Report name: FMCG Commercial Review
- Semantic source: `database/fmcg_analytics_main.duckdb`
- Audience: Commercial / Sales Managers
- Primary purpose: Track commercial performance, identify growth opportunities, monitor execution, and support recurring business reviews.
- Delivery target: Local PBIP for Power BI Desktop
- Assumptions: Import mode from the validated local DuckDB database; no Fabric publishing in this milestone.

## User decisions and constraints
- Scope: Four-page commercial review covering performance, sales versus target, growth opportunities, inventory/returns/sales-force/promotion execution.
- Interactivity: Synced Year/Month, Region, Channel and Category filters where relevant; cross-filtering within analytical pages; drillthrough-ready detail tables.
- Design direction: Corporate Cool.
- Publishing: Local only; publish later only after explicit approval.
- Accessibility: WCAG AA contrast targets, insight-led alt text, logical tab order, no color-only status encoding, searchable high-cardinality slicers.
- Data caveats: Returns are separate from sales; inventory is semi-additive snapshot data; target is Month + Region + Channel + Category; promotion overlaps are exposed through attribution flags; customer sales-rep assignments are current-state only.

## Narrative
- Core story: Are commercial results on track, where are the strongest and weakest drivers, and which execution exceptions require action?
- Audience promise: Managers can move from overall status to target variance, growth drivers and operational exceptions without exporting to Excel.
- Key questions answered:
  - What are net sales, margin, target achievement and return levels?
  - Which regions, channels, products and customers over- or under-perform target?
  - Which products/customers offer the strongest growth or margin opportunities?
  - Where are inventory, returns, sales-force and promotion exceptions?

## Design identity
- Tone: Corporate Cool — cool-grey surface, slate type, cyan primary accent, restrained enterprise density, Segoe UI fallback.
- Signature: Consistent cyan accent on primary measures and context, with slate/grey supporting marks and tabular numeric emphasis for KPI and variance values.
- Base palette: Surface `#F1F5F9`, foreground `#0F172A`, slate `#334155`, cyan `#06B6D4`, positive `#107C10`, negative `#D13438`, neutral `#64748B`.

## Page plan
1. **Commercial performance is on track**
   - Archetype: Executive Summary
   - Layout variant: B. KPI-Strip
   - Purpose: Fast business-review landing page with comparable KPI status, trend and top movers.
   - Core visuals: KPI strip, monthly net sales/gross margin trend, top region/channel movers, compact performance detail table.
   - Slicers: Year, Region, Channel.

2. **Target variance shows where action is needed**
   - Archetype: Comparative Benchmark
   - Layout variant: B. Stacked-Pairs
   - Purpose: Compare actual net sales with target at the supported monthly region/channel/category grain.
   - Core visuals: Target variance by region/channel, actual-versus-target trend, category variance detail.
   - Slicers: Year, Month, Region, Channel, Category.

3. **Growth opportunities concentrate in products and customers**
   - Archetype: Analytical Canvas
   - Layout variant: B. Inline-Slicers
   - Purpose: Explore growth, sales, volume and margin relationships across products, customers and channels.
   - Core visuals: Product/customer opportunity scatter, top products, top customers, category/channel comparison, analytical detail matrix.
   - Slicers: Year, Region, Channel.

4. **Execution exceptions need focused follow-up**
   - Archetype: Operational Monitor
   - Layout variant: A. 4-Up Status
   - Purpose: Surface inventory health, returns, sales-force coverage and promotion attribution risks.
   - Core visuals: Four status KPI treatments, latest inventory exceptions, return reason/rate view, sales-force/promotion exception table.
   - Slicers: Snapshot date, Distributor, Region.

## Model requirements
- Friendly semantic table names: Sales, Returns, Targets, Inventory Snapshot, Date, Customer, Product, Sales Force, Distributor, Promotion, Promotion Attribution.
- Import partitions should source the validated DuckDB primary file.
- Use explicit measures; hide technical keys and raw aggregable columns where appropriate.
- Date table must be marked as a date table; sort Month Name by Month Number.
- Relationships must be single-directional one-to-many from dimensions to facts.
- Do not relate Targets directly to transaction rows; use aggregated target-grain measures/views.
- Do not sum Inventory Snapshot across dates; provide latest snapshot measures.
- Do not join Returns directly into additive Sales measures; use separate return measures and explicit date context.
- Promotion attribution must retain MatchingPromotionCount and HasPromotionOverlap.

### Required measures
- Total Net Sales
- Total Gross Sales
- Total Discount Amount
- Total COGS
- Total Gross Margin
- Gross Margin %
- Total Quantity
- Transaction Count
- Active Customers
- Sales Target
- Target Achievement %
- Target Variance
- Return Amount
- Return Quantity
- Return Rate %
- Latest On Hand Quantity
- Latest In Transit Quantity
- Latest Expired Quantity
- Reorder Exception Count
- Promotion-Attributed Sales
- Promotion Overlap Sales Count
- Sales Rep Productivity

## Canonical design contract

```yaml
Design Brief:
  generated_by: powerbi-report-design
  contract_version: 1
  mode: greenfield
  design_identity:
    tone: Corporate Cool — cool-grey surface, slate type, cyan accent, enterprise density
    signature: Cyan primary-measure accents with slate context and tabular numeric emphasis on KPI and variance values
  archetype: Multi-domain Commercial Review
  color_map:
    - measure: Sales[Total Net Sales]
      color: "#06B6D4"
      tint: "#CFFAFE"
    - measure: Sales[Total Gross Margin]
      color: "#334155"
      tint: "#E2E8F0"
    - measure: Sales[Target Achievement %]
      color: "#107C10"
      tint: "#DCFCE7"
    - measure: Sales[Target Variance]
      color: "#D13438"
      tint: "#FEE2E2"
    - measure: Returns[Return Rate %]
      color: "#D13438"
      tint: "#FEE2E2"
    - measure: Inventory Snapshot[Latest On Hand Quantity]
      color: "#64748B"
      tint: "#E2E8F0"
  pages:
    - name: Commercial performance is on track
      role: landing
      archetype: Executive
      layout_variant: B
      variant_rationale: Six comparable commercial KPIs are more important than one dominant hero metric, so a full KPI strip is appropriate.
      page_background: "#F1F5F9"
      layout_summary: Full-width KPI strip followed by trend and ranked mover evidence, then a compact detail table.
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header: [1, 1, 9, 2]
            filters: [9, 1, 13, 2]
            kpis: [1, 2, 13, 4]
            trend: [1, 4, 7, 9]
            movers: [7, 4, 13, 9]
            detail: [1, 9, 13, 13]
        placements:
          - { id: page_title, region: header, kind: textbox, text: "Commercial performance is on track", purpose: "State the business-review landing message." }
          - { id: year_slicer, region: filters, kind: slicer, field_bindings: Date[Year], slicer_type: dropdown, slot: 1, of: 3 }
          - { id: region_slicer, region: filters, kind: slicer, field_bindings: Customer[Region], slicer_type: dropdown, slot: 2, of: 3 }
          - { id: channel_slicer, region: filters, kind: slicer, field_bindings: Customer[Channel], slicer_type: dropdown, slot: 3, of: 3 }
          - { id: net_sales_kpi, region: kpis, kind: cardVisual, purpose: "What is total net sales?", field_bindings: Sales[Total Net Sales], color_strategy: measure_match, slot: 1, of: 6 }
          - { id: margin_kpi, region: kpis, kind: cardVisual, purpose: "What is total gross margin?", field_bindings: Sales[Total Gross Margin], color_strategy: measure_match, slot: 2, of: 6 }
          - { id: margin_pct_kpi, region: kpis, kind: cardVisual, purpose: "What is gross margin percentage?", field_bindings: Sales[Gross Margin %], color_strategy: unique, slot: 3, of: 6 }
          - { id: achievement_kpi, region: kpis, kind: cardVisual, purpose: "Are sales achieving target?", field_bindings: Sales[Target Achievement %], color_strategy: semantic, slot: 4, of: 6 }
          - { id: customers_kpi, region: kpis, kind: cardVisual, purpose: "How many customers are active?", field_bindings: Sales[Active Customers], color_strategy: unique, slot: 5, of: 6 }
          - { id: returns_kpi, region: kpis, kind: cardVisual, purpose: "What is the return rate?", field_bindings: Returns[Return Rate %], color_strategy: semantic, slot: 6, of: 6 }
          - { id: monthly_trend, region: trend, kind: lineChart, purpose: "How are net sales and gross margin trending by month?", field_bindings: { Category: Date[YearMonth], Y: [Sales[Total Net Sales], Sales[Total Gross Margin]] }, sort_policy: natural_order, color_strategy: measure_match }
          - { id: top_movers, region: movers, kind: barChart, purpose: "Which regions or channels are the strongest and weakest movers?", field_bindings: { Category: Customer[Region], Y: Sales[Target Variance] }, sort_policy: value_desc, color_strategy: semantic }
          - { id: performance_detail, region: detail, kind: tableEx, purpose: "Which commercial slices need review?", field_bindings: [Customer[Region], Customer[Channel], Product[Category], Sales[Total Net Sales], Sales[Target Achievement %]], sort_policy: value_desc, color_strategy: none }
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: detail, pct_of_content: 36 }
          balance_rationale: KPI strip provides breadth; trend and movers explain movement; detail table supports review follow-up without creating a dominant bare card.
    - name: Target variance shows where action is needed
      role: detail
      archetype: Comparative
      layout_variant: B
      variant_rationale: The model provides actual-versus-target pairs at a fixed target grain, making stacked pair comparisons more direct than a ranking-only page.
      page_background: "#F1F5F9"
      layout_summary: Paired variance chart and actual-versus-target trend above a full-width category detail table.
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header: [1, 1, 9, 2]
            filters: [9, 1, 13, 2]
            variance: [1, 2, 7, 7]
            trend: [7, 2, 13, 7]
            detail: [1, 7, 13, 13]
        placements:
          - { id: page_title, region: header, kind: textbox, text: "Target variance shows where action is needed", purpose: "State the comparison question." }
          - { id: year_slicer, region: filters, kind: slicer, field_bindings: Date[Year], slicer_type: dropdown, slot: 1, of: 3 }
          - { id: region_slicer, region: filters, kind: slicer, field_bindings: Customer[Region], slicer_type: dropdown, slot: 2, of: 3 }
          - { id: category_slicer, region: filters, kind: slicer, field_bindings: Product[Category], slicer_type: dropdown, slot: 3, of: 3 }
          - { id: variance_by_region, region: variance, kind: barChart, purpose: "Which regions are above or below target?", field_bindings: { Category: Customer[Region], Y: Sales[Target Variance] }, sort_policy: value_desc, color_strategy: semantic, comparison_basis: Sales Target }
          - { id: actual_target_trend, region: trend, kind: lineChart, purpose: "How do actual sales and target move over time?", field_bindings: { Category: Date[YearMonth], Y: [Sales[Total Net Sales], Sales[Sales Target]] }, sort_policy: natural_order, color_strategy: measure_match, comparison_basis: Sales Target }
          - { id: variance_detail, region: detail, kind: tableEx, purpose: "Which category/channel slices explain target variance?", field_bindings: [Date[YearMonth], Customer[Region], Customer[Channel], Product[Category], Sales[Total Net Sales], Sales[Sales Target], Sales[Target Variance], Sales[Target Achievement %]], sort_policy: value_asc, color_strategy: semantic, comparison_basis: Sales Target }
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: detail, pct_of_content: 55 }
          balance_rationale: The detail table receives the largest region because target decisions require exact Month/Region/Channel/Category evidence; the two upper panels provide direction and trend context.
    - name: Growth opportunities concentrate in products and customers
      role: detail
      archetype: Analytical
      layout_variant: B
      variant_rationale: Three inline slicers keep the analytical canvas wide while supporting relationship, ranking and category/channel exploration.
      page_background: "#F1F5F9"
      layout_summary: Full-width opportunity relationship view, three supporting comparisons, and a detail matrix.
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header: [1, 1, 9, 2]
            filters: [9, 1, 13, 2]
            hero: [1, 2, 13, 6]
            products: [1, 6, 5, 10]
            customers: [5, 6, 9, 10]
            channels: [9, 6, 13, 10]
            detail: [1, 10, 13, 13]
        placements:
          - { id: page_title, region: header, kind: textbox, text: "Growth opportunities concentrate in products and customers", purpose: "State the exploration question." }
          - { id: year_slicer, region: filters, kind: slicer, field_bindings: Date[Year], slicer_type: dropdown, slot: 1, of: 3 }
          - { id: region_slicer, region: filters, kind: slicer, field_bindings: Customer[Region], slicer_type: dropdown, slot: 2, of: 3 }
          - { id: channel_slicer, region: filters, kind: slicer, field_bindings: Customer[Channel], slicer_type: dropdown, slot: 3, of: 3 }
          - { id: opportunity_scatter, region: hero, kind: scatterChart, purpose: "Which products or customers combine sales scale with margin opportunity?", field_bindings: { X: Sales[Total Net Sales], Y: Sales[Total Gross Margin], Size: Sales[Total Quantity], Details: Product[Category], Legend: Customer[Channel] }, color_strategy: unique }
          - { id: top_products, region: products, kind: barChart, purpose: "Which product categories lead on gross margin?", field_bindings: { Category: Product[Category], Y: Sales[Total Gross Margin] }, sort_policy: value_desc, color_strategy: gradient }
          - { id: top_customers, region: customers, kind: barChart, purpose: "Which customers contribute the most net sales?", field_bindings: { Category: Customer[CustomerName], Y: Sales[Total Net Sales] }, sort_policy: value_desc, color_strategy: gradient }
          - { id: channel_mix, region: channels, kind: barChart, purpose: "How do channels compare on net sales and margin?", field_bindings: { Category: Customer[Channel], Y: [Sales[Total Net Sales], Sales[Total Gross Margin]] }, sort_policy: value_desc, color_strategy: measure_match }
          - { id: opportunity_detail, region: detail, kind: tableEx, purpose: "Which products and customers should managers investigate?", field_bindings: [Product[Category], Product[Brand], Customer[CustomerName], Sales[Total Net Sales], Sales[Gross Margin %], Sales[Target Achievement %]], sort_policy: value_desc, color_strategy: none }
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: hero, pct_of_content: 36 }
          balance_rationale: The scatter is the exploratory anchor; three equal supporting panels give ranking and channel context; the bottom matrix makes findings reproducible.
    - name: Execution exceptions need focused follow-up
      role: detail
      archetype: Operational
      layout_variant: A
      variant_rationale: Inventory, returns, sales-force and promotion metrics form four distinct operational signals suitable for a balanced status layout with exception detail.
      page_background: "#F1F5F9"
      layout_summary: Four status measures at the top, two operational evidence panels, and a full-width exception table.
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header: [1, 1, 9, 2]
            filters: [9, 1, 13, 2]
            kpis: [1, 2, 13, 4]
            inventory: [1, 4, 7, 8]
            returns: [7, 4, 13, 8]
            exceptions: [1, 8, 13, 13]
        placements:
          - { id: page_title, region: header, kind: textbox, text: "Execution exceptions need focused follow-up", purpose: "State the operational action message." }
          - { id: snapshot_slicer, region: filters, kind: slicer, field_bindings: Date[Date], slicer_type: dropdown, slot: 1, of: 3 }
          - { id: distributor_slicer, region: filters, kind: slicer, field_bindings: Distributor[DistributorID], slicer_type: dropdown, slot: 2, of: 3 }
          - { id: region_slicer, region: filters, kind: slicer, field_bindings: Customer[Region], slicer_type: dropdown, slot: 3, of: 3 }
          - { id: inventory_kpi, region: kpis, kind: cardVisual, purpose: "How much latest on-hand inventory is available?", field_bindings: Inventory Snapshot[Latest On Hand Quantity], color_strategy: measure_match, slot: 1, of: 4 }
          - { id: reorder_kpi, region: kpis, kind: cardVisual, purpose: "How many distributor-product combinations are below reorder point?", field_bindings: Inventory Snapshot[Reorder Exception Count], color_strategy: semantic, slot: 2, of: 4 }
          - { id: returns_kpi, region: kpis, kind: cardVisual, purpose: "What is return rate?", field_bindings: Returns[Return Rate %], color_strategy: semantic, slot: 3, of: 4 }
          - { id: overlap_kpi, region: kpis, kind: cardVisual, purpose: "How many attributed sales have promotion overlap?", field_bindings: Promotion Attribution[Promotion Overlap Sales Count], color_strategy: semantic, slot: 4, of: 4 }
          - { id: inventory_exceptions, region: inventory, kind: barChart, purpose: "Which products and distributors need replenishment attention?", field_bindings: { Category: Product[Category], Y: Inventory Snapshot[Reorder Exception Count] }, sort_policy: value_desc, color_strategy: semantic }
          - { id: return_reasons, region: returns, kind: barChart, purpose: "Which return reasons are driving operational risk?", field_bindings: { Category: Returns[ReturnReason], Y: Returns[Return Amount] }, sort_policy: value_desc, color_strategy: gradient }
          - { id: execution_detail, region: exceptions, kind: tableEx, purpose: "Which execution exceptions need follow-up?", field_bindings: [Distributor[DistributorID], Product[Category], Inventory Snapshot[Latest On Hand Quantity], Inventory Snapshot[Reorder Exception Count], Returns[Return Rate %], Promotion Attribution[Has Promotion Overlap]], sort_policy: value_desc, color_strategy: semantic }
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: exceptions, pct_of_content: 45 }
          balance_rationale: Four status tiles support rapid scanning; inventory and return charts explain issues; the full-width exception table is the operational work surface.
  interaction_pattern:
    drill_targets: [Target variance detail, Growth opportunity detail, Execution exception detail]
    cross_filter_rules: "Default cross-filter within pages; sync Year, Region and Channel across pages; avoid cross-fact direct joins."
  accessibility:
    alt_text_strategy: "Headline + trend for KPI/trend visuals; comparison framing for target and ranking visuals; data-as-table fallback for detail matrices."
    contrast_notes: "Use #0F172A/#F1F5F9 for body text contrast, #334155/#F1F5F9 for primary marks, and pair semantic colors with labels/icons rather than color alone."
  theme:
    base: assets/base.json adapted to Corporate Cool
    user_overrides: "No existing PBIP theme exists; preserve per-type safeguards from the base theme."
```

## Implementation notes
- Build the semantic model before PBIR authoring.
- The model must use explicit measures and friendly names; do not expose raw technical IDs as primary report fields.
- Source path must remain local and configurable so the PBIP can be reopened on the same machine.
- Validate the semantic model and PBIR separately.
- Power BI Desktop is required for final reload and screenshot verification.
- Fabric publishing is intentionally deferred.
