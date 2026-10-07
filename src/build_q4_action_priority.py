"""Build a deterministic Q4 2026 commercial action-priority queue."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DB = ROOT / "database" / "fmcg_predictive_outputs.duckdb"
SOURCE_DB = ROOT / "database" / "fmcg_analytics_main.duckdb"
OUTPUT_DIR = ROOT / "processed" / "prescriptive"
AS_OF_DATE = date(2026, 9, 30)
MODEL_VERSION = "fmcg-q4-action-priority-v1.0.0"
COMPONENT_WEIGHTS = {
    "CommercialImpact": 0.30,
    "RiskOpportunitySeverity": 0.25,
    "Q4Relevance": 0.20,
    "EvidenceConfidence": 0.15,
    "Actionability": 0.10,
}
PRIORITY_THRESHOLDS = {
    "Critical": 80.0,
    "High": 65.0,
    "Medium": 45.0,
    "Low": 0.0,
}
GAP_KEYS = ("Region", "Channel", "Category")
CUSTOMER_SEGMENT_VERSION = "fmcg-customer-intelligence-v1.0.0"
INVENTORY_VERSION = "fmcg-inventory-intelligence-v1.0.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-db", type=Path, default=OUTPUT_DB)
    parser.add_argument("--source-db", type=Path, default=SOURCE_DB)
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=AS_OF_DATE)
    parser.add_argument("--run-date", type=date.fromisoformat, default=date.today())
    return parser.parse_args()


def priority_band(score: float) -> str:
    if score >= PRIORITY_THRESHOLDS["Critical"]:
        return "Critical"
    if score >= PRIORITY_THRESHOLDS["High"]:
        return "High"
    if score >= PRIORITY_THRESHOLDS["Medium"]:
        return "Medium"
    return "Low"


def percentile(values: pd.Series) -> pd.Series:
    if values.empty:
        return pd.Series(dtype=float, index=values.index)
    return values.rank(method="average", pct=True).mul(100.0)


def action_id(entity_type: str, key: str, action_type: str) -> str:
    identity = f"{MODEL_VERSION}|{entity_type}|{key}|{action_type}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def score_rows(frame: pd.DataFrame) -> pd.DataFrame:
    weighted = np.zeros(len(frame), dtype=float)
    for component, weight in COMPONENT_WEIGHTS.items():
        weighted += frame[component].to_numpy(dtype=float) * weight
    frame["PriorityScore"] = np.round(weighted, 4)
    frame["PriorityLevel"] = frame["PriorityScore"].map(priority_band)
    return frame


def build_actions(
    con: duckdb.DuckDBPyConnection,
    as_of_date: date,
    run_date: date,
    source_db: Path,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    source_path = str(source_db.resolve()).replace("'", "''")
    con.execute(f"ATTACH '{source_path}' AS analytical (READ_ONLY)")

    gaps = con.execute(
        """SELECT * FROM fact_forecast_target_gap
           WHERE ForecastMonth >= DATE '2026-10-01'
             AND ForecastMonth < DATE '2027-01-01'
           ORDER BY ForecastMonth, Region, Channel, Category"""
    ).fetchdf()
    stored_gap = gaps["ForecastTargetGap"].astype(float).copy()
    gaps = gaps.rename(
        columns={"AsOfDate": "ForecastAsOfDate", "ModelVersion": "ForecastModelVersion"}
    )
    customer_risk = con.execute(
        """SELECT * FROM fact_customer_segment_risk
           WHERE AsOfMonth = DATE '2026-09-01'
             AND ModelOrRuleVersion = ?""",
        [CUSTOMER_SEGMENT_VERSION],
    ).fetchdf()
    inventory = con.execute(
        """SELECT * FROM fact_inventory_risk
           WHERE SnapshotDate = DATE '2026-09-30'
             AND ModelOrRuleVersion = ?""",
        [INVENTORY_VERSION],
    ).fetchdf()
    customer_dim = con.execute(
        """SELECT CustomerID, Region, Channel, DistributorID
           FROM analytical.main.dim_customer"""
    ).fetchdf()
    product_dim = con.execute(
        """SELECT ProductID, Category FROM analytical.main.dim_product"""
    ).fetchdf()
    dist_map = con.execute(
        """SELECT DistributorID, COUNT(DISTINCT (Region, Channel)) AS RegionChannelPairs
           FROM analytical.main.dim_customer
           GROUP BY DistributorID"""
    ).fetchdf()
    recent_sales = con.execute(
        """SELECT s.CustomerID, p.Category, SUM(s.NetSales) AS Recent3MonthSales
           FROM analytical.main.fact_sales s
           JOIN analytical.main.dim_product p USING (ProductID)
           WHERE s.Date >= DATE '2026-07-01'
             AND s.Date <= DATE '2026-09-30'
           GROUP BY s.CustomerID, p.Category"""
    ).fetchdf()
    source_counts = {
        "target_rows": len(gaps),
        "customer_snapshot_rows": len(customer_risk),
        "inventory_snapshot_rows": len(inventory),
        "customer_dimension_rows": len(customer_dim),
        "product_dimension_rows": len(product_dim),
    }
    if as_of_date != AS_OF_DATE:
        raise ValueError(f"Build is fixed to the validated as-of date {AS_OF_DATE}.")
    if gaps.empty or customer_risk.empty or inventory.empty:
        raise ValueError("One or more required validated predictive inputs are empty.")
    if set(pd.to_datetime(gaps["ForecastMonth"]).dt.month.unique()) != {10, 11, 12}:
        raise ValueError("Forecast-vs-target input does not cover all three Q4 months.")
    if gaps[["ForecastMonth", *GAP_KEYS]].isna().any(axis=None):
        raise ValueError("Forecast-vs-target input contains null grain keys.")
    if gaps.duplicated(["ForecastMonth", *GAP_KEYS]).any():
        raise ValueError("Forecast-vs-target input has duplicate native-grain keys.")
    if gaps["SalesTarget"].isna().any():
        raise ValueError("Forecast-vs-target input contains targets with no target value.")
    if customer_risk["CustomerID"].isna().any() or customer_risk["CustomerID"].duplicated().any():
        raise ValueError("Customer snapshot keys are null or duplicated.")
    if inventory[["SnapshotDate", "DistributorID", "ProductID"]].isna().any(axis=None):
        raise ValueError("Inventory snapshot contains null keys.")
    if inventory.duplicated(["SnapshotDate", "DistributorID", "ProductID"]).any():
        raise ValueError("Inventory snapshot keys are duplicated.")
    formula_difference = float(
        np.max(np.abs(stored_gap.to_numpy() - (gaps["ForecastSales"] - gaps["SalesTarget"]).to_numpy()))
    )
    if formula_difference > 0.01:
        raise ValueError(f"Stored forecast-target gap does not reconcile: max difference {formula_difference}.")

    gaps["ForecastMonth"] = pd.to_datetime(gaps["ForecastMonth"]).dt.date
    if gaps.duplicated(["ForecastMonth", *GAP_KEYS]).any():
        raise ValueError("Forecast-vs-target input has duplicate native-grain keys.")
    gaps["ForecastTargetGap"] = gaps["ForecastSales"] - gaps["SalesTarget"]
    gaps["ForecastTargetGapPct"] = np.where(
        gaps["SalesTarget"].ne(0),
        gaps["ForecastTargetGap"] / gaps["SalesTarget"],
        np.nan,
    )

    q4_by_month = (
        gaps.groupby("ForecastMonth", as_index=False)
        .agg(
            ForecastSales=("ForecastSales", "sum"),
            SalesTarget=("SalesTarget", "sum"),
            ForecastTargetGap=("ForecastTargetGap", "sum"),
            GapRows=("ForecastTargetGap", "size"),
            NegativeGapRows=("ForecastTargetGap", lambda x: int((x < 0).sum())),
            PositiveGapRows=("ForecastTargetGap", lambda x: int((x > 0).sum())),
        )
    )
    q4_by_month["ForecastTargetGapPct"] = (
        q4_by_month["ForecastTargetGap"] / q4_by_month["SalesTarget"]
    )
    q4_totals = {
        "ForecastSales": float(gaps["ForecastSales"].sum()),
        "SalesTarget": float(gaps["SalesTarget"].sum()),
        "ForecastTargetGap": float(gaps["ForecastTargetGap"].sum()),
        "NegativeGapAmount": float(gaps.loc[gaps.ForecastTargetGap < 0, "ForecastTargetGap"].sum()),
        "PositiveGapOffset": float(gaps.loc[gaps.ForecastTargetGap > 0, "ForecastTargetGap"].sum()),
        "GapRows": len(gaps),
        "NegativeGapRows": int((gaps.ForecastTargetGap < 0).sum()),
        "PositiveGapRows": int((gaps.ForecastTargetGap > 0).sum()),
        "ZeroTargetRows": int((gaps.SalesTarget == 0).sum()),
    }
    concentration = (
        gaps.groupby(list(GAP_KEYS), as_index=False)
        .agg(
            Q4ForecastSales=("ForecastSales", "sum"),
            Q4SalesTarget=("SalesTarget", "sum"),
            Q4ForecastTargetGap=("ForecastTargetGap", "sum"),
            Q4NegativeGapAmount=(
                "ForecastTargetGap",
                lambda x: float(x[x < 0].sum()),
            ),
            MonthsWithNegativeGap=(
                "ForecastTargetGap",
                lambda x: int((x < 0).sum()),
            ),
        )
    )
    concentration["Q4GapPct"] = (
        concentration["Q4ForecastTargetGap"] / concentration["Q4SalesTarget"]
    )
    concentration["DeficitSharePct"] = np.where(
        q4_totals["NegativeGapAmount"] != 0,
        concentration["Q4NegativeGapAmount"] / q4_totals["NegativeGapAmount"] * 100,
        0,
    )
    concentration["Q4ForecastTargetGap"] = concentration["Q4ForecastTargetGap"].round(2)
    concentration["Q4NegativeGapAmount"] = concentration["Q4NegativeGapAmount"].round(2)
    concentration = concentration.sort_values("Q4NegativeGapAmount").reset_index(drop=True)

    # Historical customer sales are assigned using current customer geography;
    # product category is directly observed on the transaction.
    recent_sales = recent_sales.merge(customer_dim[["CustomerID", "Region", "Channel"]], on="CustomerID", how="left")
    recent_sales["Recent3MonthSales"] = recent_sales["Recent3MonthSales"].fillna(0.0)
    deficit_combinations = set(
        tuple(x)
        for x in gaps.loc[gaps.ForecastTargetGap < 0, GAP_KEYS].drop_duplicates().itertuples(index=False, name=None)
    )
    recent_sales["Q4GapRelevantSales"] = [
        amount if (region, channel, category) in deficit_combinations else 0.0
        for region, channel, category, amount in recent_sales[
            ["Region", "Channel", "Category", "Recent3MonthSales"]
        ].itertuples(index=False, name=None)
    ]
    customer_relevance = (
        recent_sales.groupby("CustomerID", as_index=False)
        .agg(
            Recent3MonthSales=("Recent3MonthSales", "sum"),
            Q4GapRelevantSales=("Q4GapRelevantSales", "sum"),
        )
    )
    customer_relevance["Q4RelevantSalesShare"] = np.divide(
        customer_relevance["Q4GapRelevantSales"],
        customer_relevance["Recent3MonthSales"],
        out=np.zeros(len(customer_relevance), dtype=float),
        where=customer_relevance["Recent3MonthSales"].to_numpy() > 0,
    )
    customer_risk = customer_risk.merge(customer_relevance, on="CustomerID", how="left")
    customer_risk = customer_risk.merge(
        customer_dim[["CustomerID", "Region", "Channel"]].rename(
            columns={"Region": "CustomerRegion", "Channel": "CustomerChannel"}
        ),
        on="CustomerID",
        how="left",
    )
    customer_risk[["Recent3MonthSales", "Q4GapRelevantSales", "Q4RelevantSalesShare"]] = (
        customer_risk[["Recent3MonthSales", "Q4GapRelevantSales", "Q4RelevantSalesShare"]].fillna(0.0)
    )
    customer_risk["CommercialSegment"] = customer_risk["CommercialSegment"].str.upper()
    customer_core_high = customer_risk.loc[
        customer_risk["CommercialSegment"].eq("CORE / MAINTAIN")
        & customer_risk["DeclineRiskLevel"].eq("High")
        & customer_risk["Trailing12MonthSales"].gt(0)
    ].copy()
    customer_potential = customer_risk.loc[
        customer_risk["CommercialSegment"].eq("POTENTIAL")
        & customer_risk["MomentumScore"].ge(70)
        & customer_risk["EngagementScore"].ge(50)
        & customer_risk["Trailing12MonthSales"].gt(0)
    ].copy()

    # Distributor geography is deliberately not joined: every distributor
    # serves multiple region/channel pairs, so only product Category is safe.
    inventory = inventory.merge(product_dim, on="ProductID", how="left")
    inventory = inventory.merge(dist_map, on="DistributorID", how="left")
    inventory["Trailing3CompleteMonthsSalesQuantity"] = inventory[
        "Trailing3CompleteMonthsSalesQuantity"
    ].fillna(0)
    inventory["DemandHistoryAvailableFlag"] = inventory[
        "DemandHistoryAvailableFlag"
    ].fillna(False)
    inventory["ReorderExceptionFlag"] = inventory["ReorderExceptionFlag"].fillna(False)
    inventory["CoveragePressureLevel"] = inventory["CoveragePressureLevel"].fillna("Low")
    inventory["CategoryQ4NegativeGapAmount"] = inventory["Category"].map(
        concentration.groupby("Category")["Q4NegativeGapAmount"].sum().to_dict()
    ).fillna(0.0)
    inventory_candidates = inventory.loc[
        inventory["DemandHistoryAvailableFlag"]
        & inventory["Trailing3CompleteMonthsSalesQuantity"].gt(0)
        & (
            inventory["CoveragePressureLevel"].isin(["Medium", "High"])
            | inventory["ReorderExceptionFlag"]
        )
        & inventory["CategoryQ4NegativeGapAmount"].lt(0)
    ].copy()

    gap_actions = gaps.loc[gaps["ForecastTargetGap"] < 0].copy()
    gap_actions["ActionEntityType"] = "Q4 target-gap segment"
    gap_actions["EntityKey"] = gap_actions.apply(
        lambda r: f"{r.ForecastMonth}|{r.Region}|{r.Channel}|{r.Category}", axis=1
    )
    gap_actions["ActionType"] = "Q4_GAP_REVIEW"
    gap_actions["CommercialImpact"] = percentile(gap_actions["ForecastTargetGap"].abs())
    gap_actions["RiskOpportunitySeverity"] = (
        gap_actions["ForecastTargetGapPct"].abs().mul(100).clip(upper=100)
    )
    gap_actions["Q4Relevance"] = 100.0
    gap_actions["EvidenceConfidence"] = 72.0
    gap_actions["Actionability"] = 90.0
    gap_actions["EvidenceConfidenceRationale"] = (
        "Validated forecast benchmark; 21 months of history and seven rolling origins."
    )
    gap_actions["ActionabilityRationale"] = (
        "Native target grain identifies the accountable commercial intersection for review."
    )
    gap_actions["RecommendationTemplate"] = (
        "Review the Q4 forecast-to-target shortfall for this month, region, channel, "
        "and category; validate local drivers and agree an owner and next review."
    )
    gap_actions["CurrentExecutionExceptionFlag"] = False
    gap_actions["ForwardRiskFeatureFlag"] = False

    customer_actions = []
    for frame, action_type, segment, risk_level, severity, confidence, template in [
        (
            customer_core_high,
            "CORE_HIGH_DECLINE_REVIEW",
            "CORE / MAINTAIN",
            "High",
            100.0,
            80.0,
            "Review the customer's observed sales trend and account context with the "
            "account team; confirm retention needs and an appropriate next step.",
        ),
        (
            customer_potential,
            "POTENTIAL_GROWTH_VALIDATION",
            "POTENTIAL",
            "Not applicable",
            50.0,
            65.0,
            "Validate the observed momentum and engagement with the account team; "
            "confirm customer interest and capacity before recording any opportunity.",
        ),
    ]:
        if frame.empty:
            continue
        items = frame.copy()
        items["ActionEntityType"] = "Customer"
        items["EntityKey"] = items["CustomerID"].astype(str)
        items["ActionType"] = action_type
        items["CommercialImpact"] = percentile(items["Trailing12MonthSales"])
        if action_type == "POTENTIAL_GROWTH_VALIDATION":
            items["RiskOpportunitySeverity"] = (
                (items["MomentumScore"].fillna(0) + items["EngagementScore"].fillna(0))
                .div(2)
                .clip(upper=100)
            )
        else:
            items["RiskOpportunitySeverity"] = severity
        items["Q4Relevance"] = items["Q4RelevantSalesShare"].mul(100).clip(0, 100)
        items["EvidenceConfidence"] = confidence
        items["Actionability"] = 75.0
        items["EvidenceConfidenceRationale"] = (
            "Decline tier has temporal holdout validation but is not probability-calibrated."
            if action_type == "CORE_HIGH_DECLINE_REVIEW"
            else "Potential is an as-of relative segment with momentum and engagement; no uplift is estimated."
        )
        items["ActionabilityRationale"] = (
            "Account review can validate context and next steps; no prescribed offer or recovery value."
        )
        items["RecommendationTemplate"] = template
        items["CurrentExecutionExceptionFlag"] = False
        items["ForwardRiskFeatureFlag"] = action_type == "CORE_HIGH_DECLINE_REVIEW"
        items["CustomerSegment"] = segment
        items["DeclineRiskLevel"] = risk_level if action_type == "POTENTIAL_GROWTH_VALIDATION" else items["DeclineRiskLevel"]
        customer_actions.append(items)
    customer_actions = pd.concat(customer_actions, ignore_index=True) if customer_actions else pd.DataFrame()

    if not inventory_candidates.empty:
        inventory_candidates["ActionEntityType"] = "Distributor-product inventory position"
        inventory_candidates["EntityKey"] = (
            inventory_candidates["SnapshotDate"].astype(str)
            + "|"
            + inventory_candidates["DistributorID"].astype(str)
            + "|"
            + inventory_candidates["ProductID"].astype(str)
        )
        inventory_candidates["ActionType"] = np.where(
            inventory_candidates["CoveragePressureLevel"].isin(["Medium", "High"]),
            "INVENTORY_COVERAGE_PRESSURE_REVIEW",
            "REORDER_EXCEPTION_DEMAND_REVIEW",
        )
        inventory_candidates["CommercialImpact"] = percentile(
            inventory_candidates["Trailing3CompleteMonthsSalesQuantity"].astype(float)
        )
        inventory_candidates["RiskOpportunitySeverity"] = np.maximum(
            inventory_candidates["CoveragePressureScore"].astype(float),
            np.where(inventory_candidates["ReorderExceptionFlag"], 65.0, 0.0),
        ).clip(upper=100)
        category_gap_abs = concentration.groupby("Category")["Q4NegativeGapAmount"].sum().abs()
        inventory_candidates["Q4Relevance"] = inventory_candidates["Category"].map(
            lambda category: 60.0
            + 40.0
            * abs(float(category_gap_abs.get(category, 0.0)))
            / max(float(category_gap_abs.max()), 1.0)
        )
        inventory_candidates["EvidenceConfidence"] = np.where(
            inventory_candidates["ReorderExceptionFlag"], 85.0, 70.0
        )
        inventory_candidates["Actionability"] = 80.0
        inventory_candidates["EvidenceConfidenceRationale"] = np.where(
            inventory_candidates["ReorderExceptionFlag"],
            "Current snapshot directly records On Hand below Reorder Point; geographic Q4 match is not asserted.",
            "Coverage pressure is an analytical screening feature; no lead-time or service-level calibration.",
        )
        inventory_candidates["ActionabilityRationale"] = (
            "Current position and recent demand support a review under normal replenishment policy; no quantity prescribed."
        )
        inventory_candidates["RecommendationTemplate"] = (
            "Review current On Hand, Reorder Point, recent demand, and inbound status "
            "under normal replenishment policy before making a quantity decision."
        )
        inventory_candidates["CurrentExecutionExceptionFlag"] = inventory_candidates[
            "ReorderExceptionFlag"
        ].astype(bool)
        inventory_candidates["ForwardRiskFeatureFlag"] = inventory_candidates[
            "CoveragePressureLevel"
        ].isin(["Medium", "High"])
        inventory_candidates["Q4MappingScope"] = (
            "Product Category only; distributor maps to multiple Region × Channel pairs."
        )
    else:
        inventory_candidates = pd.DataFrame()

    actions = pd.concat(
        [gap_actions, customer_actions, inventory_candidates],
        ignore_index=True,
        sort=False,
    )
    if actions.empty:
        raise ValueError("No action candidates met the approved evidence-based rules.")
    actions = score_rows(actions)
    actions["ActionID"] = [
        action_id(row.ActionEntityType, row.EntityKey, row.ActionType)
        for row in actions.itertuples(index=False)
    ]
    actions["AsOfDate"] = as_of_date
    actions["RunDate"] = run_date
    actions["ModelOrRuleVersion"] = MODEL_VERSION
    actions["ComponentWeights"] = json.dumps(COMPONENT_WEIGHTS, sort_keys=True)
    actions["PriorityThresholds"] = json.dumps(PRIORITY_THRESHOLDS, sort_keys=True)
    actions["Q4GapRelevantSalesShare"] = actions.get("Q4RelevantSalesShare", pd.Series(0.0, index=actions.index)).fillna(0.0)
    actions["ForecastTargetGap"] = actions.get("ForecastTargetGap", pd.Series(np.nan, index=actions.index))
    actions["ForecastTargetGapPct"] = actions.get("ForecastTargetGapPct", pd.Series(np.nan, index=actions.index))
    actions["Trailing12MonthSales"] = actions.get("Trailing12MonthSales", pd.Series(np.nan, index=actions.index))
    actions["Trailing12MonthGrossMargin"] = actions.get("Trailing12MonthGrossMargin", pd.Series(np.nan, index=actions.index))
    actions["DeclineRiskLevel"] = actions.get("DeclineRiskLevel", pd.Series(pd.NA, index=actions.index))
    actions["CommercialSegment"] = actions.get("CommercialSegment", pd.Series(pd.NA, index=actions.index))
    actions["DistributorID"] = actions.get("DistributorID", pd.Series(pd.NA, index=actions.index))
    actions["ProductID"] = actions.get("ProductID", pd.Series(pd.NA, index=actions.index))
    actions["InventoryCategory"] = actions.get("Category", pd.Series(pd.NA, index=actions.index))
    actions["CategoryQ4NegativeGapAmount"] = actions.get("CategoryQ4NegativeGapAmount", pd.Series(np.nan, index=actions.index))
    actions["Q4MappingScope"] = actions.get("Q4MappingScope", pd.Series("Native target grain", index=actions.index)).fillna("Native target grain")
    actions["CurrentExecutionExceptionFlag"] = actions["CurrentExecutionExceptionFlag"].fillna(False).astype(bool)
    actions["ForwardRiskFeatureFlag"] = actions["ForwardRiskFeatureFlag"].fillna(False).astype(bool)

    output_columns = [
        "ActionID", "ActionEntityType", "EntityKey", "ActionType", "PriorityLevel",
        "PriorityScore", *COMPONENT_WEIGHTS.keys(), "ComponentWeights", "PriorityThresholds",
        "EvidenceConfidenceRationale", "ActionabilityRationale", "RecommendationTemplate",
        "ForecastMonth", "Region", "Channel", "Category", "ForecastSales", "SalesTarget",
        "ForecastTargetGap", "ForecastTargetGapPct", "CustomerID", "CommercialSegment",
        "DeclineRiskLevel", "Trailing12MonthSales", "Trailing12MonthGrossMargin",
        "Recent3MonthSales", "Q4GapRelevantSalesShare", "CustomerRegion",
        "CustomerChannel", "MomentumScore", "EngagementScore", "ValueScore",
        "Trailing3MonthSalesAverage", "AsOfMonth", "DistributorID", "ProductID",
        "InventoryCategory", "OnHandQuantity", "InTransitQuantity", "ReorderPoint",
        "Trailing3CompleteMonthsSalesQuantity", "CoveragePressureLevel",
        "CoveragePressureScore", "ReorderExceptionFlag", "SnapshotFreshnessDays",
        "ExpiredQuantity", "RecentDailySalesVelocity", "OnHandCoverageDays",
        "AvailableCoverageDays", "DemandHistoryAvailableFlag",
        "CurrentExecutionExceptionFlag", "ForwardRiskFeatureFlag",
        "CategoryQ4NegativeGapAmount", "Q4MappingScope", "ForecastMethod",
        "ForecastHorizon", "ForecastAsOfDate", "ForecastModelVersion",
        "AsOfDate", "RunDate", "ModelOrRuleVersion",
    ]
    for column in output_columns:
        if column not in actions:
            actions[column] = pd.NA
    actions = actions[output_columns].sort_values(
        ["PriorityScore", "CommercialImpact"], ascending=[False, False]
    ).reset_index(drop=True)

    # Sensitivity: perturb each component weight by five points, renormalizing
    # all other weights proportionally, with the same fixed priority thresholds.
    sensitivity_rows = []
    baseline_ranks = actions["PriorityScore"].rank(method="min", ascending=False)
    baseline_top_100 = set(actions.loc[baseline_ranks <= 100, "ActionID"])
    for component in COMPONENT_WEIGHTS:
        for direction in (-0.05, 0.05):
            changed = dict(COMPONENT_WEIGHTS)
            revised = max(0.0, changed[component] + direction)
            remainder_before = 1.0 - changed[component]
            remainder_after = 1.0 - revised
            changed[component] = revised
            for other in COMPONENT_WEIGHTS:
                if other != component:
                    changed[other] = (
                        COMPONENT_WEIGHTS[other] * remainder_after / remainder_before
                    )
            score = sum(actions[name] * changed[name] for name in COMPONENT_WEIGHTS)
            rank = score.rank(method="min", ascending=False)
            top_100 = set(actions.loc[rank <= 100, "ActionID"])
            levels = score.map(priority_band)
            sensitivity_rows.append(
                {
                    "Scenario": f"{component}_{'plus' if direction > 0 else 'minus'}_5pp",
                    "ChangedComponent": component,
                    "WeightChangePoints": direction * 100,
                    "Weights": json.dumps(changed, sort_keys=True),
                    "Top100OverlapCount": len(baseline_top_100 & top_100),
                    "Top100OverlapPct": len(baseline_top_100 & top_100) / max(len(baseline_top_100), 1) * 100,
                    "SpearmanRankCorrelation": float(
                        np.corrcoef(baseline_ranks.to_numpy(), rank.to_numpy())[0, 1]
                    ),
                    "PriorityBandChangedCount": int((levels != actions["PriorityLevel"]).sum()),
                }
            )
    sensitivity = pd.DataFrame(sensitivity_rows)

    customer_summary = pd.DataFrame(
        [
            {
                "CustomerGroup": "Core / Maintain + validated High Decline Risk",
                "Customers": len(customer_core_high),
                "Trailing12MonthSales": float(customer_core_high["Trailing12MonthSales"].sum()),
                "Trailing12MonthGrossMargin": float(customer_core_high["Trailing12MonthGrossMargin"].sum()),
                "Recent3MonthSales": float(customer_core_high["Recent3MonthSales"].sum()),
                "Q4GapRelevantRecentSales": float(customer_core_high["Q4GapRelevantSales"].sum()),
            },
            {
                "CustomerGroup": "Potential with momentum >= 70 and engagement >= 50",
                "Customers": len(customer_potential),
                "Trailing12MonthSales": float(customer_potential["Trailing12MonthSales"].sum()),
                "Trailing12MonthGrossMargin": float(customer_potential["Trailing12MonthGrossMargin"].sum()),
                "Recent3MonthSales": float(customer_potential["Recent3MonthSales"].sum()),
                "Q4GapRelevantRecentSales": float(customer_potential["Q4GapRelevantSales"].sum()),
            },
        ]
    )
    inventory_summary = (
        inventory_candidates.groupby(["Category", "CoveragePressureLevel"], as_index=False)
        .agg(
            Positions=("ProductID", "size"),
            ReorderExceptions=("ReorderExceptionFlag", "sum"),
            RecentDemandQuantity=("Trailing3CompleteMonthsSalesQuantity", "sum"),
            Q4CategoryNegativeGap=("CategoryQ4NegativeGapAmount", "first"),
        )
        if not inventory_candidates.empty
        else pd.DataFrame(columns=["Category", "CoveragePressureLevel", "Positions", "ReorderExceptions", "RecentDemandQuantity", "Q4CategoryNegativeGap"])
    )
    return actions, {
        "source_counts": source_counts,
        "gap_formula_max_abs_difference": formula_difference,
        "q4_totals": q4_totals,
        "q4_by_month": q4_by_month,
        "customer_summary": customer_summary,
        "inventory_summary": inventory_summary,
        "concentration": concentration,
        "sensitivity": sensitivity,
        "dist_map": dist_map,
        "customer_core_high": customer_core_high,
        "customer_potential": customer_potential,
        "inventory_candidates": inventory_candidates,
    }, q4_by_month, concentration, sensitivity


def main() -> None:
    args = parse_args()
    if not args.output_db.is_file() or not args.source_db.is_file():
        raise FileNotFoundError("Required predictive output or analytical database is missing.")
    if args.output_db.resolve() == args.source_db.resolve():
        raise ValueError("Output database must remain separate from analytical source.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.output_db))
    try:
        actions, metadata, q4_by_month, concentration, sensitivity = build_actions(
            con, args.as_of_date, args.run_date, args.source_db
        )
        duplicate_action_ids = int(actions["ActionID"].duplicated().sum())
        null_identity_rows = int(
            actions[["ActionID", "ActionEntityType", "EntityKey", "ActionType"]]
            .isna()
            .any(axis=1)
            .sum()
        )
        if duplicate_action_ids or null_identity_rows:
            raise ValueError(
                f"Action key validation failed: duplicates={duplicate_action_ids}, "
                f"null identities={null_identity_rows}"
            )
        if not actions["PriorityScore"].between(0, 100).all():
            raise ValueError("Priority score is outside [0, 100].")
        if actions["ActionType"].str.contains("INACTIVITY", case=False).any():
            raise ValueError("Provisional inactivity must not independently trigger actions.")
        if actions["RecommendationTemplate"].isna().any():
            raise ValueError("Every action must use a deterministic recommendation template.")

        config = pd.DataFrame(
            [
                {"Component": name, "Weight": weight, "ScaleMin": 0, "ScaleMax": 100}
                for name, weight in COMPONENT_WEIGHTS.items()
            ]
        )
        thresholds = pd.DataFrame(
            [
                {"PriorityLevel": level, "MinimumScoreInclusive": score}
                for level, score in PRIORITY_THRESHOLDS.items()
            ]
        )
        validation = {
            "model_or_rule_version": MODEL_VERSION,
            "as_of_date": args.as_of_date.isoformat(),
            "run_date": args.run_date.isoformat(),
            "source_counts": metadata["source_counts"],
            "q4_totals": metadata["q4_totals"],
            "q4_gap_formula_max_abs_difference": metadata["gap_formula_max_abs_difference"],
            "action_rows": len(actions),
            "unique_action_ids": int(actions["ActionID"].nunique()),
            "duplicate_action_ids": duplicate_action_ids,
            "null_identity_rows": null_identity_rows,
            "priority_score_range": [
                float(actions["PriorityScore"].min()),
                float(actions["PriorityScore"].max()),
            ],
            "priority_level_distribution": {
                str(k): int(v)
                for k, v in actions["PriorityLevel"].value_counts().to_dict().items()
            },
            "action_type_distribution": {
                str(k): int(v)
                for k, v in actions["ActionType"].value_counts().to_dict().items()
            },
            "customer_priority_summary": metadata["customer_summary"].to_dict(orient="records"),
            "potential_growth_opportunity_summary": metadata["customer_summary"].iloc[1].to_dict(),
            "inventory_priority_summary": metadata["inventory_summary"].to_dict(orient="records"),
            "inventory_geography_mapping": {
                "distinct_region_channel_pairs_per_distributor": sorted(
                    metadata["dist_map"]["RegionChannelPairs"].astype(int).unique().tolist()
                ),
                "rule": "Join only Product Category for inventory-to-gap relevance; do not assign distributor inventory to a region or channel.",
            },
            "validation_checks": {
                "forecast_gap_native_grain_unique": True,
                "forecast_months_complete_oct_dec_2026": True,
                "forecast_targets_present": True,
                "forecast_gap_formula_reconciles_within_one_cent": metadata[
                    "gap_formula_max_abs_difference"
                ] <= 0.01,
                "customer_snapshot_key_unique": True,
                "inventory_snapshot_keys_unique": True,
                "action_ids_unique": duplicate_action_ids == 0,
                "action_identity_non_null": null_identity_rows == 0,
                "priority_scores_within_0_100": bool(actions["PriorityScore"].between(0, 100).all()),
                "recommendations_are_deterministic_templates": bool(actions["RecommendationTemplate"].notna().all()),
                "no_inactivity_trigger": not bool(actions["ActionType"].str.contains("INACTIVITY", case=False).any()),
                "no_sales_recovery_or_lost_sales_estimates": True,
                "no_exact_inventory_quantity_prescribed": True,
            },
            "weight_sensitivity": sensitivity.to_dict(orient="records"),
        }

        tables = {
            "fact_q4_action_priority": actions,
            "q4_gap_concentration": concentration,
            "q4_priority_component_config": config,
            "q4_priority_threshold_config": thresholds,
            "q4_priority_weight_sensitivity": sensitivity,
            "q4_customer_priority_summary": metadata["customer_summary"],
            "q4_inventory_relevance_summary": metadata["inventory_summary"],
        }
        for table_name, frame in tables.items():
            temp_name = f"_{table_name}_build"
            con.register(temp_name, frame)
            con.execute(f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM "{temp_name}"')
            con.unregister(temp_name)
            frame.to_csv(OUTPUT_DIR / f"{table_name}.csv", index=False)
        q4_by_month.to_csv(OUTPUT_DIR / "q4_gap_by_month.csv", index=False)
        with (OUTPUT_DIR / "q4_priority_validation.json").open("w", encoding="utf-8") as stream:
            json.dump(validation, stream, indent=2, default=str)
        print(json.dumps(validation, indent=2, default=str))
    finally:
        con.close()


if __name__ == "__main__":
    main()
