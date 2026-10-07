# FMCG Commercial Analytics & AI-Assisted Decision System

An end-to-end FMCG commercial analytics practice project that transforms raw transactional data into management insights and action priorities.

The project demonstrates how **Python, SQL, DuckDB, Power BI and AI-assisted development** can work together across the full analytics lifecycle:

**Data Engineering → Diagnostic Analytics → Predictive Analytics → Prescriptive Analytics → Executive Decision Support**

> **Project Status:** Active development  
> The analytical framework is complete and the Power BI reporting layer is currently being refined for final portfolio presentation.

---

## 1. Business Objective

The project is designed around practical commercial management questions:

- How is the business performing against target?
- Where are sales gaps concentrated?
- What is driving performance across region, channel, category and customer?
- Which customers require protection or further growth validation?
- What commercial performance is likely in the next quarter?
- Which inventory conditions may require operational review?
- Where should management focus first?

The objective is not simply to build dashboards.

The project connects **commercial performance, customer behaviour, forecasting and execution signals** into a structured decision-support process.

---

## 2. Analytics Journey

```text
Raw FMCG Data
      ↓
Python Data Pipeline
      ↓
Data Quality & Validation
      ↓
DuckDB Analytical Model
      ↓
Power BI Semantic Model
      ↓
Diagnostic Analytics
      ↓
Predictive Analytics
      ↓
Prescriptive Prioritisation
      ↓
Executive Decision Support
```

The analytical journey follows three core questions:

### Diagnostic Analytics
**What happened, where did it happen, and what factors are associated with the result?**

### Predictive Analytics
**What is likely to happen next?**

### Prescriptive Analytics
**Given the available evidence, where should management investigate and act first?**

---

## 3. Dataset

The project uses a synthetic FMCG dataset designed to simulate a realistic commercial environment.

Main data includes:

- **620,000 sales transactions**
- **6,500 customers**
- **180 products**
- Monthly commercial targets
- Sales returns
- Distributor inventory snapshots
- Sales-force information
- Promotion information

Sales history covers **January 2025 to September 2026**, with commercial targets extending through **December 2026**.

The data model separates dimensions and facts to preserve the correct analytical grain.

---

## 4. Data & Analytical Architecture

The project uses a layered architecture:

```text
CSV Source Data
      ↓
Python
Ingestion / Validation / Transformation
      ↓
Processed Analytical Tables
      ↓
DuckDB
Relational Analytical Layer
      ↓
Power BI Semantic Model
      ↓
DAX Measures
      ↓
Management Dashboard
```

### Core Dimensions

- Customer
- Product
- Date
- Distributor
- Sales Force
- Promotion

### Core Facts

- Sales
- Returns
- Targets
- Inventory
- Promotion Attribution

Additional predictive and prescriptive analytical outputs are integrated into the reporting model.

---

## 5. Diagnostic Analytics

The diagnostic layer investigates performance through a structured drill path:

```text
Company
  ↓
Region
  ↓
Channel
  ↓
Category
  ↓
Brand
  ↓
SKU
  ↓
Customer / Distributor / Sales Rep
```

Key analytical areas include:

- Net Sales
- Sales Target
- Target Achievement
- Target Variance
- Month-on-Month Growth
- Sales Quantity
- Active Customers
- Average Selling Price
- Discount
- Gross Margin
- Returns
- Inventory conditions
- Promotion attribution

The dashboard is designed to move from:

**WHAT happened → WHERE → WHY → WHO**

rather than presenting isolated KPIs.

---

## 6. Predictive Analytics

### Q4 Sales Forecast

Several forecasting approaches were backtested using rolling historical periods.

The selected benchmark model was a **Trailing 3-Month Average**, based on historical validation performance.

Historical backtest:

- **WAPE: 5.67%**
- **Bias: +0.14%**

### Q4 2026 Outlook

| Metric | Result |
|---|---:|
| Q4 Forecast Sales | 46.50B |
| Q4 Sales Target | 48.84B |
| Forecast Target Gap | -2.34B |
| Projected Target Achievement | 95.22% |

The projected gap widens through the quarter:

| Month | Forecast Gap | Gap % |
|---|---:|---:|
| October | -0.445B | -2.79% |
| November | -0.586B | -3.64% |
| December | -1.306B | -7.77% |

December therefore represents the largest projected monthly shortfall.

---

## 7. Customer Intelligence

Customer analytics combines commercial behaviour with segmentation and risk signals.

### Core / Maintain — Protect Existing Business

**617 Core / Maintain customers** are identified with validated High Decline Risk.

Their existing trailing-12-month sales exposure is approximately:

**20.18B**

This value represents the existing business base associated with these customers.

It is **not an estimate of expected revenue loss**.

The management objective is to identify high-value accounts requiring deeper commercial review and potential retention action.

### Potential — Validate Growth Opportunities

**153 customers** meet the qualified Potential criteria.

Their trailing-12-month business base is approximately:

**3.76B**

These customers require further validation of factors such as:

- Momentum
- Engagement
- Purchase frequency
- Assortment
- Category penetration
- Commercial capacity

The existing business base should not be interpreted as guaranteed incremental revenue.

---

## 8. Inventory Intelligence

Inventory analytics is used as an execution-screening layer.

Current signals include:

- **525 High Coverage Pressure positions**
- **602 Reorder Exceptions**

The analysis considers factors such as:

- On Hand inventory
- Reorder Point
- In Transit inventory
- Recent demand
- Inventory coverage

These signals identify positions requiring review.

They should **not** be interpreted as confirmed stockouts, lost sales or guaranteed replenishment requirements.

---

## 9. Prescriptive Analytics

The prescriptive layer combines multiple analytical signals into a management review framework.

The objective is not to automatically prescribe a commercial decision.

Instead, it answers:

> **Where should management investigate and act first?**

### Q4 Priority Framework

Priority Score combines:

```text
Commercial Impact       30%
Risk / Opportunity      25%
Q4 Relevance            20%
Evidence Confidence     15%
Actionability           10%
```

Priority levels:

| Score | Priority |
|---|---|
| >= 80 | Critical |
| >= 65 and < 80 | High |
| >= 45 and < 65 | Medium |
| < 45 | Low |

The score is a **management review ranking**.

It is not a probability of loss, recovery rate or revenue estimate.

---

## 10. Q4 Management Framework

The current analytical evidence supports four management priorities:

### 1. FOCUS

Start with the largest negative **Region × Channel × Category** target gaps.

The five largest negative commercial intersections represent approximately **28.8% of gross negative shortfall**.

### 2. PROTECT

Prioritise valuable Core / Maintain customers showing validated decline risk.

Review account-level sales trends, purchase behaviour, assortment and field execution before defining retention actions.

### 3. GROW

Validate qualified Potential customers.

Investigate whether positive momentum and engagement can translate into greater purchase frequency, category penetration or assortment expansion.

### 4. ENABLE

Review inventory coverage and reorder exceptions where they may affect execution in priority commercial categories.

---

## 11. Important Analytical Guardrails

A major principle of the project is maintaining the correct **data grain**.

### Target & Forecast

Native analytical grain:

**Month × Region × Channel × Category**

Target gaps must not be directly interpreted at individual customer level.

### Customer Analytics

Customer analysis operates at:

**Customer × As-of Month**

Customer exposure represents existing historical business, not expected loss or guaranteed opportunity.

### Inventory

Inventory is **semi-additive**.

Inventory snapshots should not be summed across time.

### Predictive Signals

Risk and forecast outputs are decision-support signals rather than deterministic outcomes.

---

## 12. Power BI Reporting Structure

The current Power BI solution covers the full analytical journey:

### Executive Summary
Management view of Q4 outlook, key concerns and action priorities.

### Commercial Diagnostic Overview
Overall commercial health and major performance signals.

### Target & Growth Drivers
Target performance and location of commercial gaps.

### Product, Price & Profitability
Product contribution, quantity, ASP, discount and margin analysis.

### Customer & Field Contribution
Customer, distributor and sales-force contribution.

### Execution — Returns, Inventory & Promotions
Operational and execution-related commercial signals.

### Commercial Outlook & Outlet Risk
Forecast, customer risk and inventory outlook.

### Q4 Target Recovery & Action Priorities
Prescriptive management-priority framework.

### Dashboard Guide
Explains the analytical investigation journey and how each page supports decision-making.

### Metric & Matrix Dictionary
Definitions, formulas, analytical grain and interpretation guidance.

---

## 13. Technology Stack

| Area | Technology |
|---|---|
| Data Processing | Python |
| Analytical Database | DuckDB |
| Data Modelling | SQL |
| Semantic Model | Power BI / TMDL |
| Business Measures | DAX |
| Reporting | Power BI |
| Development Environment | VS Code |
| Version Control | Git / GitHub |
| AI-Assisted Development | ChatGPT / GitHub Copilot |

---

## 14. AI-Assisted Analytics Approach

AI is used as a development and analytical assistant rather than as the calculation engine.

The working principle is:

```text
Business Question
      ↓
Analytical Logic
      ↓
Data Grain & Model
      ↓
Python / SQL / DAX
      ↓
Validation
      ↓
Business Interpretation
      ↓
Management Action
```

Python, SQL and DAX perform deterministic calculations.

AI supports activities such as:

- analytical planning
- code generation
- debugging
- model design
- documentation
- interpretation
- report authoring

All material analytical outputs are validated before being used for business interpretation.

---

## 15. Current Project Status

Completed:

- Data ingestion and validation
- Analytical data model
- DuckDB database
- Power BI semantic model
- Diagnostic analytics
- Sales forecasting
- Customer segmentation and decline-risk analysis
- Inventory intelligence
- Prescriptive Q4 priority engine
- Executive reporting framework
- Dashboard documentation

Current work:

- Final Executive Summary refinement
- Dashboard storytelling and presentation polish
- Portfolio documentation
- Dashboard screenshots and GitHub presentation

---

## 16. Next Steps

Before final portfolio publication:

- Finalise Executive Summary storytelling
- Complete visual QA across Power BI pages
- Add dashboard screenshots to this README
- Clean development backup files from the public-facing repository
- Refine project documentation for recruiter / hiring-manager review

---

## Disclaimer

This is a **synthetic FMCG analytics practice project** created for learning and portfolio demonstration.

The data does not represent the actual commercial performance of any real company.