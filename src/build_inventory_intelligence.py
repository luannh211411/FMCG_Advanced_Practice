"""Build explainable current-status and coverage signals for inventory."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FEATURE_DB = ROOT / "database" / "fmcg_predictive_features.duckdb"
ANALYTICS_DB = ROOT / "database" / "fmcg_analytics_main.duckdb"
OUTPUT_DB = ROOT / "database" / "fmcg_predictive_outputs.duckdb"
OUTPUT_DIR = ROOT / "processed" / "predictive"
MODEL_VERSION = "fmcg-inventory-intelligence-v1.0.0"
REFERENCE_START = pd.Timestamp("2025-04-01")
REFERENCE_END = pd.Timestamp("2025-12-31")
SCORE_REFERENCE_START = pd.Timestamp("2025-07-01")
SCORE_REFERENCE_END = pd.Timestamp("2025-12-31")
LOW_COVERAGE_QUANTILE = 0.25
VERY_LOW_COVERAGE_QUANTILE = 0.10
HIGH_COVERAGE_QUANTILE = 0.75
VERY_HIGH_COVERAGE_QUANTILE = 0.90
TREND_LOW_QUANTILE = 0.25
TREND_HIGH_QUANTILE = 0.75
PRESSURE_MEDIUM_QUANTILE = 0.75
PRESSURE_HIGH_QUANTILE = 0.90
EXCESS_MEDIUM_QUANTILE = 0.75
EXCESS_HIGH_QUANTILE = 0.90


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    return value


def require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def quantile(values: pd.Series, probability: float, name: str) -> float:
    observed = values.dropna()
    if observed.empty:
        raise ValueError(f"No observations available to estimate {name}.")
    return float(observed.quantile(probability))


def load_inputs(
    con: duckdb.DuckDBPyConnection,
    feature_db: Path,
    analytics_db: Path,
    as_of_date: date,
) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    feature_path = str(feature_db.resolve()).replace("'", "''")
    analytics_path = str(analytics_db.resolve()).replace("'", "''")
    con.execute(f"ATTACH '{feature_path}' AS features (READ_ONLY)")
    con.execute(f"ATTACH '{analytics_path}' AS analytics (READ_ONLY)")

    data = con.execute(
        "SELECT * FROM features.main.feature_inventory_risk "
        "ORDER BY SnapshotDate, DistributorID, ProductID"
    ).fetchdf()
    required = {
        "SnapshotDate",
        "DistributorID",
        "ProductID",
        "OnHandQuantity",
        "InTransitQuantity",
        "ReorderPoint",
        "ExpiredQuantity",
        "AvailableInventoryQty",
        "SnapshotFreshnessDays",
        "CurrentReorderException",
        "Trailing3CompleteMonthsSalesQuantity",
        "Prior3CompleteMonthsSalesQuantity",
        "SalesVelocityQuantityPerDay",
        "DemandTrendPct",
        "InventoryCoverageDaysProxy",
    }
    require_columns(data, required, "feature_inventory_risk")
    if data.empty:
        raise ValueError("The validated inventory feature table is empty.")
    keys = ["SnapshotDate", "DistributorID", "ProductID"]
    if data[keys].isna().any(axis=None):
        raise ValueError("Inventory feature grain contains null keys.")
    if data.duplicated(keys).any():
        raise ValueError("Inventory features are not unique at snapshot grain.")

    data["SnapshotDate"] = pd.to_datetime(data["SnapshotDate"])
    first_sales_date, last_sales_date = con.execute(
        "SELECT MIN(Date), MAX(Date) FROM analytics.main.fact_sales"
    ).fetchone()
    latest_snapshot = data["SnapshotDate"].max().date()
    if latest_snapshot != as_of_date:
        raise ValueError(
            f"Requested as-of date {as_of_date} does not match latest snapshot "
            f"{latest_snapshot}."
        )
    if pd.Timestamp(last_sales_date) < data["SnapshotDate"].max():
        raise ValueError("Sales cutoff precedes the latest inventory snapshot.")
    return (
        data,
        pd.Timestamp(first_sales_date).to_period("M").to_timestamp(),
        pd.Timestamp(last_sales_date).to_period("M").to_timestamp(),
    )


def add_signals(
    data: pd.DataFrame,
    first_sales_month: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, float], dict[str, int]]:
    frame = data.copy()
    frame["SourceDemandTrendPct"] = frame["DemandTrendPct"]
    snapshot_month = frame["SnapshotDate"].dt.to_period("M").dt.to_timestamp()
    frame["AsOfDate"] = frame["SnapshotDate"].dt.date

    recent_start = snapshot_month - pd.DateOffset(months=3)
    prior_start = snapshot_month - pd.DateOffset(months=6)
    frame["DemandHistoryAvailableFlag"] = recent_start >= first_sales_month
    frame["DemandTrendHistoryAvailableFlag"] = prior_start >= first_sales_month
    recent_days = (snapshot_month - recent_start).dt.days
    prior_days = (recent_start - prior_start).dt.days
    frame["RecentDailySalesVelocity"] = (
        frame["Trailing3CompleteMonthsSalesQuantity"] / recent_days
    ).where(frame["DemandHistoryAvailableFlag"])
    frame["PriorDailySalesVelocity"] = (
        frame["Prior3CompleteMonthsSalesQuantity"] / prior_days
    ).where(frame["DemandTrendHistoryAvailableFlag"])
    frame.loc[
        frame["RecentDailySalesVelocity"].le(0), "RecentDailySalesVelocity"
    ] = np.nan
    frame.loc[
        frame["PriorDailySalesVelocity"].le(0), "PriorDailySalesVelocity"
    ] = np.nan
    frame["DemandTrendPct"] = frame["DemandTrendPct"].where(
        frame["DemandTrendHistoryAvailableFlag"]
    )
    frame["OnHandCoverageDays"] = (
        frame["OnHandQuantity"] / frame["RecentDailySalesVelocity"]
    ).where(frame["RecentDailySalesVelocity"] > 0)
    frame["AvailableCoverageDays"] = (
        frame["AvailableInventoryQty"] / frame["RecentDailySalesVelocity"]
    ).where(frame["RecentDailySalesVelocity"] > 0)

    frame["ReorderExceptionFlag"] = frame["CurrentReorderException"].eq(1)
    frame["ExpiredInventoryFlag"] = frame["ExpiredQuantity"].gt(0)
    frame["ZeroOnHandFlag"] = frame["OnHandQuantity"].eq(0)
    frame["PositiveInTransitFlag"] = frame["InTransitQuantity"].gt(0)
    frame["NoRecentDemandFlag"] = (
        frame["DemandHistoryAvailableFlag"]
        & frame["Trailing3CompleteMonthsSalesQuantity"].eq(0)
    ).where(frame["DemandHistoryAvailableFlag"], pd.NA).astype("boolean")
    frame["ZeroOnHandWithRecentDemandFlag"] = (
        frame["DemandHistoryAvailableFlag"]
        & frame["ZeroOnHandFlag"]
        & frame["Trailing3CompleteMonthsSalesQuantity"].gt(0)
    ).where(frame["DemandHistoryAvailableFlag"], pd.NA).astype("boolean")

    coverage_reference = frame.loc[
        frame["SnapshotDate"].between(REFERENCE_START, REFERENCE_END)
        & frame["DemandHistoryAvailableFlag"]
    ]
    trend_reference = frame.loc[
        frame["SnapshotDate"].between(SCORE_REFERENCE_START, SCORE_REFERENCE_END)
        & frame["DemandTrendHistoryAvailableFlag"]
    ]
    if coverage_reference.empty or trend_reference.empty:
        raise ValueError("Insufficient mature reference history for thresholds.")

    thresholds = {
        "OnHandCoverageP10Days": quantile(
            coverage_reference["OnHandCoverageDays"],
            VERY_LOW_COVERAGE_QUANTILE,
            "very-low on-hand coverage",
        ),
        "OnHandCoverageP25Days": quantile(
            coverage_reference["OnHandCoverageDays"],
            LOW_COVERAGE_QUANTILE,
            "low on-hand coverage",
        ),
        "OnHandCoverageP75Days": quantile(
            coverage_reference["OnHandCoverageDays"],
            HIGH_COVERAGE_QUANTILE,
            "high on-hand coverage",
        ),
        "OnHandCoverageP90Days": quantile(
            coverage_reference["OnHandCoverageDays"],
            VERY_HIGH_COVERAGE_QUANTILE,
            "very-high on-hand coverage",
        ),
        "AvailableCoverageP25Days": quantile(
            coverage_reference["AvailableCoverageDays"],
            LOW_COVERAGE_QUANTILE,
            "low available coverage",
        ),
        "DemandTrendP25Pct": quantile(
            trend_reference["DemandTrendPct"],
            TREND_LOW_QUANTILE,
            "weak/falling demand trend",
        ),
        "DemandTrendP75Pct": quantile(
            trend_reference["DemandTrendPct"],
            TREND_HIGH_QUANTILE,
            "rising demand trend",
        ),
    }
    samples = {
        "CoverageThresholdRows": int(coverage_reference["OnHandCoverageDays"].notna().sum()),
        "DemandTrendThresholdRows": int(trend_reference["DemandTrendPct"].notna().sum()),
    }

    frame["LowOnHandCoverageFlag"] = (
        frame["OnHandCoverageDays"] <= thresholds["OnHandCoverageP25Days"]
    ).where(frame["OnHandCoverageDays"].notna(), pd.NA).astype("boolean")
    frame["VeryLowOnHandCoverageFlag"] = (
        frame["OnHandCoverageDays"] <= thresholds["OnHandCoverageP10Days"]
    ).where(frame["OnHandCoverageDays"].notna(), pd.NA).astype("boolean")
    frame["LowAvailableCoverageFlag"] = (
        frame["AvailableCoverageDays"] <= thresholds["AvailableCoverageP25Days"]
    ).where(frame["AvailableCoverageDays"].notna(), pd.NA).astype("boolean")
    frame["DemandIncreasingFlag"] = (
        frame["DemandTrendPct"] >= thresholds["DemandTrendP75Pct"]
    ).where(frame["DemandTrendPct"].notna(), pd.NA).astype("boolean")
    frame["DemandDecliningFlag"] = (
        frame["DemandTrendPct"] <= thresholds["DemandTrendP25Pct"]
    ).where(frame["DemandTrendPct"].notna(), pd.NA).astype("boolean")

    frame["CoveragePressureScore"] = (
        frame["ReorderExceptionFlag"].astype(int) * 35
        + frame["LowOnHandCoverageFlag"].fillna(False).astype(int) * 25
        + frame["LowAvailableCoverageFlag"].fillna(False).astype(int) * 20
        + frame["ZeroOnHandWithRecentDemandFlag"].fillna(False).astype(int) * 20
        + frame["DemandIncreasingFlag"].fillna(False).astype(int) * 10
    )
    transit_support = (
        frame["LowOnHandCoverageFlag"].fillna(False)
        & frame["PositiveInTransitFlag"]
        & (frame["AvailableCoverageDays"] > thresholds["AvailableCoverageP25Days"])
    )
    frame["CoveragePressureScore"] = (
        frame["CoveragePressureScore"] - transit_support.astype(int) * 10
    ).clip(lower=0, upper=100)
    pressure_reference = frame.loc[
        frame["SnapshotDate"].between(SCORE_REFERENCE_START, SCORE_REFERENCE_END)
    ]
    samples["PressureScoreThresholdRows"] = len(pressure_reference)
    thresholds["CoveragePressureScoreP75"] = quantile(
        pressure_reference["CoveragePressureScore"],
        PRESSURE_MEDIUM_QUANTILE,
        "medium coverage-pressure score",
    )
    thresholds["CoveragePressureScoreP90"] = quantile(
        pressure_reference["CoveragePressureScore"],
        PRESSURE_HIGH_QUANTILE,
        "high coverage-pressure score",
    )
    frame["CoveragePressureLevel"] = np.select(
        [
            frame["CoveragePressureScore"] >= thresholds["CoveragePressureScoreP90"],
            frame["CoveragePressureScore"] >= thresholds["CoveragePressureScoreP75"],
        ],
        ["High", "Medium"],
        default="Low",
    )

    frame["ExcessSlowMovingScore"] = (
        (frame["OnHandCoverageDays"] >= thresholds["OnHandCoverageP75Days"]).fillna(False).astype(int) * 40
        + (frame["OnHandCoverageDays"] >= thresholds["OnHandCoverageP90Days"]).fillna(False).astype(int) * 20
        + frame["DemandDecliningFlag"].fillna(False).astype(int) * 25
        + (
            frame["NoRecentDemandFlag"].fillna(False)
            & frame["OnHandQuantity"].gt(0)
        ).astype(int)
        * 50
    ).clip(lower=0, upper=100)
    frame.loc[frame["OnHandQuantity"].le(0), "ExcessSlowMovingScore"] = 0
    excess_reference = frame.loc[
        frame.index.isin(pressure_reference.index)
        & (frame["OnHandQuantity"] > 0)
        & frame["DemandHistoryAvailableFlag"]
    ]
    samples["ExcessScoreThresholdRows"] = len(excess_reference)
    thresholds["ExcessSlowMovingScoreP75"] = quantile(
        excess_reference["ExcessSlowMovingScore"],
        EXCESS_MEDIUM_QUANTILE,
        "medium excess/slow-moving score",
    )
    thresholds["ExcessSlowMovingScoreP90"] = quantile(
        excess_reference["ExcessSlowMovingScore"],
        EXCESS_HIGH_QUANTILE,
        "high excess/slow-moving score",
    )
    frame["ExcessSlowMovingLevel"] = np.select(
        [
            frame["ExcessSlowMovingScore"] >= thresholds["ExcessSlowMovingScoreP90"],
            frame["ExcessSlowMovingScore"] >= thresholds["ExcessSlowMovingScoreP75"],
        ],
        ["High", "Medium"],
        default="Low",
    )
    frame.loc[frame["OnHandQuantity"].le(0), "ExcessSlowMovingLevel"] = "Low"
    frame["ExcessSlowMovingFlag"] = frame["ExcessSlowMovingLevel"].isin(
        ["Medium", "High"]
    )
    frame["LowCoveragePressureFlag"] = frame["CoveragePressureLevel"].isin(
        ["Medium", "High"]
    )

    def primary_driver(row: pd.Series) -> str:
        def is_true(value: Any) -> bool:
            return bool(value) if pd.notna(value) else False

        if row["ZeroOnHandFlag"] and row["DemandHistoryAvailableFlag"] and row[
            "Trailing3CompleteMonthsSalesQuantity"
        ] > 0:
            return "Zero On Hand with recent demand"
        if row["ReorderExceptionFlag"] and is_true(row["LowOnHandCoverageFlag"]):
            return "On Hand below Reorder Point with low coverage"
        if row["ReorderExceptionFlag"]:
            return "On Hand below Reorder Point"
        if is_true(row["VeryLowOnHandCoverageFlag"]) and is_true(
            row["DemandIncreasingFlag"]
        ):
            return "Rising demand with very low On-Hand coverage"
        if is_true(row["VeryLowOnHandCoverageFlag"]):
            return "Very low On-Hand coverage"
        if is_true(row["NoRecentDemandFlag"]) and row["OnHandQuantity"] > 0:
            return "Inventory present with no recent demand"
        if (
            row["ExcessSlowMovingLevel"] == "High"
            and is_true(row["DemandDecliningFlag"])
        ):
            return "High coverage with declining demand"
        if row["ExpiredInventoryFlag"]:
            return "Existing expired inventory"
        if row["ExcessSlowMovingLevel"] == "Medium":
            return "High relative On-Hand coverage"
        if row["LowCoveragePressureFlag"]:
            return "Relative coverage / demand pressure"
        return "No elevated analytical signal"

    frame["PrimaryInventoryRiskDriver"] = frame.apply(primary_driver, axis=1)
    frame["ModelOrRuleVersion"] = MODEL_VERSION
    return frame, thresholds, samples


def threshold_config(
    thresholds: dict[str, float],
    samples: dict[str, int],
    first_sales_month: pd.Timestamp,
    last_sales_month: pd.Timestamp,
) -> pd.DataFrame:
    labels = {
        "OnHandCoverageP10Days": "Very-low On-Hand coverage analytical reference",
        "OnHandCoverageP25Days": "Low On-Hand coverage analytical reference",
        "OnHandCoverageP75Days": "High On-Hand coverage analytical reference",
        "OnHandCoverageP90Days": "Very-high On-Hand coverage analytical reference",
        "AvailableCoverageP25Days": "Low On-Hand plus In-Transit coverage analytical reference",
        "DemandTrendP25Pct": "Weak/falling demand trend analytical reference",
        "DemandTrendP75Pct": "Rising demand trend analytical reference",
        "CoveragePressureScoreP75": "Medium coverage-pressure score boundary",
        "CoveragePressureScoreP90": "High coverage-pressure score boundary",
        "ExcessSlowMovingScoreP75": "Medium excess/slow-moving score boundary",
        "ExcessSlowMovingScoreP90": "High excess/slow-moving score boundary",
    }
    rows = []
    for name, value in thresholds.items():
        rows.append(
            {
                "ThresholdName": name,
                "ThresholdValue": value,
                "Unit": (
                    "days"
                    if "Coverage" in name and "Score" not in name
                    else "ratio"
                    if "Trend" in name
                    else "score points"
                ),
                "Method": (
                    "Empirical reference-period quantile; analytical only, not a "
                    "lead-time or service-level policy."
                ),
                "Interpretation": labels[name],
                "CoverageReferenceStart": REFERENCE_START.date(),
                "CoverageReferenceEnd": REFERENCE_END.date(),
                "TrendAndScoreReferenceStart": SCORE_REFERENCE_START.date(),
                "TrendAndScoreReferenceEnd": SCORE_REFERENCE_END.date(),
                "CoverageReferenceRows": samples["CoverageThresholdRows"],
                "TrendReferenceRows": samples["DemandTrendThresholdRows"],
                "PressureScoreReferenceRows": samples[
                    "PressureScoreThresholdRows"
                ],
                "ExcessScoreReferenceRows": samples["ExcessScoreThresholdRows"],
                "FirstSalesMonth": first_sales_month.date(),
                "LastSalesMonth": last_sales_month.date(),
                "ModelOrRuleVersion": MODEL_VERSION,
            }
        )
    return pd.DataFrame(rows)


def signal_distribution(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for snapshot, group in frame.groupby("SnapshotDate", sort=True):
        valid_coverage = group["OnHandCoverageDays"].dropna()
        valid_trend = group["DemandTrendPct"].dropna()
        rows.append(
            {
                "SnapshotDate": snapshot.date(),
                "Positions": len(group),
                "DemandHistoryAvailablePositions": int(
                    group["DemandHistoryAvailableFlag"].sum()
                ),
                "DemandTrendHistoryAvailablePositions": int(
                    group["DemandTrendHistoryAvailableFlag"].sum()
                ),
                "CurrentReorderExceptions": int(group["ReorderExceptionFlag"].sum()),
                "ZeroOnHandPositions": int(group["ZeroOnHandFlag"].sum()),
                "ExpiredInventoryPositions": int(group["ExpiredInventoryFlag"].sum()),
                "ExpiredQuantityAtSnapshot": int(group["ExpiredQuantity"].sum()),
                "NoRecentDemandPositions": int(
                    group["NoRecentDemandFlag"].fillna(False).sum()
                ),
                "PositiveInTransitPositions": int(group["PositiveInTransitFlag"].sum()),
                "LowCoveragePressurePositions": int(
                    group["LowCoveragePressureFlag"].sum()
                ),
                "HighCoveragePressurePositions": int(
                    group["CoveragePressureLevel"].eq("High").sum()
                ),
                "ExcessSlowMovingPositions": int(
                    group["ExcessSlowMovingFlag"].sum()
                ),
                "HighExcessSlowMovingPositions": int(
                    group["ExcessSlowMovingLevel"].eq("High").sum()
                ),
                "OnHandQtyAtSnapshot": int(group["OnHandQuantity"].sum()),
                "InTransitQtyAtSnapshot": int(group["InTransitQuantity"].sum()),
                "AvailableInventoryQtyAtSnapshot": int(
                    group["AvailableInventoryQty"].sum()
                ),
                "RecentSalesQuantityAtSnapshot": int(
                    group["Trailing3CompleteMonthsSalesQuantity"].sum()
                ),
                "MedianOnHandCoverageDays": (
                    float(valid_coverage.median()) if len(valid_coverage) else None
                ),
                "MedianAvailableCoverageDays": (
                    float(group["AvailableCoverageDays"].median())
                    if group["AvailableCoverageDays"].notna().any()
                    else None
                ),
                "MedianDemandTrendPct": (
                    float(valid_trend.median()) if len(valid_trend) else None
                ),
                "ModelOrRuleVersion": MODEL_VERSION,
            }
        )
    return pd.DataFrame(rows)


def transition_summary(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.sort_values(["DistributorID", "ProductID", "SnapshotDate"]).copy()
    key = ["DistributorID", "ProductID"]
    prev_date = ordered.groupby(key)["SnapshotDate"].shift()
    current_month_index = ordered["SnapshotDate"].dt.year * 12 + ordered[
        "SnapshotDate"
    ].dt.month
    prior_month_index = prev_date.dt.year * 12 + prev_date.dt.month
    consecutive = (current_month_index - prior_month_index).eq(1)
    rows = []
    signals = {
        "CurrentReorderException": ("ReorderExceptionFlag", False),
        "ExpiredInventory": ("ExpiredInventoryFlag", False),
        "NoRecentDemand": ("NoRecentDemandFlag", True),
        "LowCoveragePressure": ("LowCoveragePressureFlag", False),
        "HighCoveragePressure": ("CoveragePressureLevel", True),
        "ExcessSlowMoving": ("ExcessSlowMovingFlag", False),
    }
    for name, (column, level_signal) in signals.items():
        prev = ordered.groupby(key)[column].shift()
        valid = consecutive & prev.notna() & ordered[column].notna()
        current_values = ordered.loc[valid, column]
        previous_values = prev.loc[valid]
        if level_signal:
            pairs = pd.DataFrame(
                {
                    "FromLevel": previous_values.astype(str),
                    "ToLevel": current_values.astype(str),
                }
            )
            counts = pairs.groupby(["FromLevel", "ToLevel"]).size()
            for (from_level, to_level), count in counts.items():
                rows.append(
                    {
                        "Signal": name,
                        "FromState": from_level,
                        "ToState": to_level,
                        "Transitions": int(count),
                        "TransitionRate": float(count / len(pairs)),
                        "ModelOrRuleVersion": MODEL_VERSION,
                    }
                )
        else:
            before = previous_values.fillna(False).astype(bool)
            after = current_values.fillna(False).astype(bool)
            pairs = pd.DataFrame({"FromState": before, "ToState": after})
            counts = pairs.groupby(["FromState", "ToState"]).size()
            for (from_state, to_state), count in counts.items():
                rows.append(
                    {
                        "Signal": name,
                        "FromState": str(bool(from_state)),
                        "ToState": str(bool(to_state)),
                        "Transitions": int(count),
                        "TransitionRate": float(count / len(pairs)),
                        "ModelOrRuleVersion": MODEL_VERSION,
                    }
                )
    return pd.DataFrame(rows)


def threshold_sensitivity(
    frame: pd.DataFrame,
    current_pressure_p75: float,
    current_pressure_p90: float,
    current_excess_p75: float,
    current_excess_p90: float,
) -> pd.DataFrame:
    current = frame.loc[frame["SnapshotDate"] == frame["SnapshotDate"].max()].copy()
    coverage_reference = frame.loc[
        frame["SnapshotDate"].between(REFERENCE_START, REFERENCE_END)
        & frame["DemandHistoryAvailableFlag"]
    ]
    trend_reference = frame.loc[
        frame["SnapshotDate"].between(SCORE_REFERENCE_START, SCORE_REFERENCE_END)
        & frame["DemandTrendHistoryAvailableFlag"]
    ]
    rows = []
    for scenario, q, trend_rising_q, trend_falling_q in (
        ("Strict (P20 coverage / P80 trend)", 0.20, 0.80, 0.20),
        ("Base (P25 coverage / P75 and P25 trend)", 0.25, 0.75, 0.25),
        ("Broad (P30 coverage / P70 and P30 trend)", 0.30, 0.70, 0.30),
    ):
        low_oh = quantile(
            coverage_reference["OnHandCoverageDays"], q, f"{scenario} on-hand"
        )
        low_av = quantile(
            coverage_reference["AvailableCoverageDays"], q, f"{scenario} available"
        )
        rising = quantile(
            trend_reference["DemandTrendPct"],
            trend_rising_q,
            f"{scenario} rising demand",
        )
        falling = quantile(
            trend_reference["DemandTrendPct"],
            trend_falling_q,
            f"{scenario} falling demand",
        )
        low_oh_flag = current["OnHandCoverageDays"] <= low_oh
        low_av_flag = current["AvailableCoverageDays"] <= low_av
        rising_flag = current["DemandTrendPct"] >= rising
        zero_demand_flag = current["ZeroOnHandWithRecentDemandFlag"].fillna(False)
        score = (
            current["ReorderExceptionFlag"].astype(int) * 35
            + low_oh_flag.fillna(False).astype(int) * 25
            + low_av_flag.fillna(False).astype(int) * 20
            + zero_demand_flag.astype(int) * 20
            + rising_flag.fillna(False).astype(int) * 10
        )
        transit_support = (
            low_oh_flag.fillna(False)
            & current["PositiveInTransitFlag"]
            & (current["AvailableCoverageDays"] > low_av)
        )
        score = (score - transit_support.astype(int) * 10).clip(0, 100)
        pressure_level = np.select(
            [score >= current_pressure_p90, score >= current_pressure_p75],
            ["High", "Medium"],
            default="Low",
        )

        high_coverage_quantile, very_high_coverage_quantile = (
            (0.80, 0.95)
            if scenario.startswith("Strict")
            else (0.70, 0.85)
            if scenario.startswith("Broad")
            else (0.75, 0.90)
        )
        high_onhand = current["OnHandCoverageDays"] >= quantile(
            coverage_reference["OnHandCoverageDays"],
            high_coverage_quantile,
            f"{scenario} high on-hand",
        )
        very_high_onhand = current["OnHandCoverageDays"] >= quantile(
            coverage_reference["OnHandCoverageDays"],
            very_high_coverage_quantile,
            f"{scenario} very-high on-hand",
        )
        falling_flag = current["DemandTrendPct"] <= falling
        no_demand = current["NoRecentDemandFlag"].fillna(False)
        excess_score = (
            high_onhand.fillna(False).astype(int) * 40
            + very_high_onhand.fillna(False).astype(int) * 20
            + falling_flag.fillna(False).astype(int) * 25
            + (no_demand & current["OnHandQuantity"].gt(0)).astype(int) * 50
        ).clip(0, 100)
        excess_score = excess_score.where(current["OnHandQuantity"] > 0, 0)
        excess_level = np.select(
            [excess_score >= current_excess_p90, excess_score >= current_excess_p75],
            ["High", "Medium"],
            default="Low",
        )
        excess_level = np.where(current["OnHandQuantity"] > 0, excess_level, "Low")
        rows.append(
            {
                "Scenario": scenario,
                "CurrentPositions": len(current),
                "CoveragePressurePositions": int(
                    pd.Series(pressure_level).isin(["Medium", "High"]).sum()
                ),
                "HighCoveragePressurePositions": int(
                    pd.Series(pressure_level).eq("High").sum()
                ),
                "ExcessSlowMovingPositions": int(
                    pd.Series(excess_level).isin(["Medium", "High"]).sum()
                ),
                "HighExcessSlowMovingPositions": int(
                    pd.Series(excess_level).eq("High").sum()
                ),
                "LowOnHandCoverageDaysThreshold": low_oh,
                "LowAvailableCoverageDaysThreshold": low_av,
                "DemandTrendRisingThreshold": rising,
                "DemandTrendFallingThreshold": falling,
                "ModelOrRuleVersion": MODEL_VERSION,
            }
        )
    return pd.DataFrame(rows)


def future_demand_association(
    con: duckdb.DuckDBPyConnection,
    frame: pd.DataFrame,
    max_sales_month: pd.Timestamp,
) -> pd.DataFrame:
    eligible = frame.loc[
        frame["DemandTrendHistoryAvailableFlag"]
        & frame["SnapshotDate"].dt.to_period("M").dt.to_timestamp().le(
            max_sales_month - pd.DateOffset(months=3)
        )
    ].copy()
    if eligible.empty:
        raise ValueError("No inventory snapshots have complete subsequent demand windows.")
    con.register("inventory_association_input", eligible[
        ["SnapshotDate", "DistributorID", "ProductID"]
    ])
    future = con.execute(
        """
        WITH monthly_sales AS (
            SELECT
                DistributorID,
                ProductID,
                date_trunc('month', "Date")::DATE AS MonthStart,
                SUM(Qty) AS SalesQuantity
            FROM analytics.main.vw_sales_analysis
            GROUP BY 1, 2, 3
        ),
        future_demand AS (
            SELECT
                s.SnapshotDate,
                s.DistributorID,
                s.ProductID,
                COALESCE(SUM(m.SalesQuantity), 0) AS Future3MonthSalesQuantity
            FROM inventory_association_input s
            LEFT JOIN monthly_sales m
                ON m.DistributorID = s.DistributorID
                AND m.ProductID = s.ProductID
                AND m.MonthStart > date_trunc('month', s.SnapshotDate)
                AND m.MonthStart <= date_trunc('month', s.SnapshotDate)
                    + INTERVAL '3 months'
            GROUP BY 1, 2, 3
        )
        SELECT * FROM future_demand
        """
    ).fetchdf()
    con.unregister("inventory_association_input")
    joined = eligible.merge(
        future,
        on=["SnapshotDate", "DistributorID", "ProductID"],
        how="left",
        validate="one_to_one",
    )
    joined["Future3MonthSalesQuantity"] = joined[
        "Future3MonthSalesQuantity"
    ].fillna(0)
    joined["FutureToRecentDemandRatio"] = (
        joined["Future3MonthSalesQuantity"]
        / joined["Trailing3CompleteMonthsSalesQuantity"].replace(0, np.nan)
    )
    rows = []
    for signal, column, levels in (
        ("CoveragePressure", "CoveragePressureLevel", ["Low", "Medium", "High"]),
        ("ExcessSlowMoving", "ExcessSlowMovingLevel", ["Low", "Medium", "High"]),
    ):
        for level in levels:
            group = joined.loc[joined[column] == level]
            ratio = group["FutureToRecentDemandRatio"].dropna()
            rows.append(
                {
                    "Signal": signal,
                    "SignalLevel": level,
                    "SnapshotPositions": len(group),
                    "DistinctSnapshots": int(group["SnapshotDate"].nunique()),
                    "MedianFutureToRecent3MonthDemandRatio": (
                        float(ratio.median()) if len(ratio) else None
                    ),
                    "FutureDemandBelowRecentPositions": int(
                        (
                            group["Future3MonthSalesQuantity"]
                            < group["Trailing3CompleteMonthsSalesQuantity"]
                        ).sum()
                    ),
                    "FutureDemandAboveRecentPositions": int(
                        (
                            group["Future3MonthSalesQuantity"]
                            > group["Trailing3CompleteMonthsSalesQuantity"]
                        ).sum()
                    ),
                    "FutureZeroDemandPositions": int(
                        group["Future3MonthSalesQuantity"].eq(0).sum()
                    ),
                    "Interpretation": (
                        "Descriptive non-causal association only; overlapping "
                        "three-month windows and current distributor mapping."
                    ),
                    "ModelOrRuleVersion": MODEL_VERSION,
                }
            )
    return pd.DataFrame(rows)


def make_support_assessment() -> pd.DataFrame:
    entries = [
        (
            "Current Reorder Exception",
            "SUPPORTED",
            "On Hand < Reorder Point is directly observable and reconciled to the fact.",
            "Current execution status only; not a future stockout.",
        ),
        (
            "Low Coverage / Replenishment Pressure",
            "PARTIALLY SUPPORTED",
            "Pre-snapshot sales velocity, On Hand, In Transit and reorder point support a relative pressure signal.",
            "No lead time/order cadence; severity is analytical, not service-level policy.",
        ),
        (
            "Excess / Slow-Moving",
            "PARTIALLY SUPPORTED",
            "Positive On Hand combined with relatively high coverage and weak/no recent demand supports a screening signal.",
            "Not obsolescence, expiry, excess value, or write-off estimate.",
        ),
        (
            "Expired Inventory Condition",
            "SUPPORTED",
            "Expired quantity is recorded in the current inventory snapshot.",
            "Current condition only; no future expiry inference.",
        ),
        (
            "Future Stockout Risk",
            "NOT SUPPORTED",
            "No replenishment lead time, order cadence, or full future purchase-order feed.",
            "No stockout probability or predicted stockout date.",
        ),
        (
            "Future Expiry Risk",
            "NOT SUPPORTED",
            "No lot/batch expiry dates or shelf-life details.",
            "No future expiry prediction or estimated expired quantity.",
        ),
    ]
    return pd.DataFrame(
        entries,
        columns=[
            "CandidateRiskType",
            "SupportClassification",
            "Evidence",
            "Boundary",
        ],
    ).assign(ModelOrRuleVersion=MODEL_VERSION)


def run(args: argparse.Namespace) -> dict[str, Any]:
    for input_path in (args.feature_db, args.analytics_db):
        if not input_path.is_file():
            raise FileNotFoundError(f"Required read-only input not found: {input_path}")
    if args.output_db.resolve() in {
        args.feature_db.resolve(),
        args.analytics_db.resolve(),
    }:
        raise ValueError("Output database cannot overwrite a read-only source.")
    if args.as_of_date != date(2026, 9, 30):
        raise ValueError("Build 4 is scoped to the 2026-09-30 inventory snapshot.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.output_db))
    try:
        source, first_sales_month, max_sales_month = load_inputs(
            con, args.feature_db, args.analytics_db, args.as_of_date
        )
        frame, thresholds, samples = add_signals(source, first_sales_month)
        support = make_support_assessment()
        distribution = signal_distribution(frame)
        transitions = transition_summary(frame)
        sensitivity = threshold_sensitivity(
            frame,
            thresholds["CoveragePressureScoreP75"],
            thresholds["CoveragePressureScoreP90"],
            thresholds["ExcessSlowMovingScoreP75"],
            thresholds["ExcessSlowMovingScoreP90"],
        )
        association = future_demand_association(con, frame, max_sales_month)
        latest_date = frame["SnapshotDate"].max()
        latest = frame.loc[frame["SnapshotDate"] == latest_date].copy()

        threshold_table = threshold_config(
            thresholds, samples, first_sales_month, max_sales_month
        )
        frame["RunDate"] = args.run_date
        output_columns = [
            "SnapshotDate",
            "AsOfDate",
            "DistributorID",
            "ProductID",
            "OnHandQuantity",
            "InTransitQuantity",
            "AvailableInventoryQty",
            "ReorderPoint",
            "ExpiredQuantity",
            "SnapshotFreshnessDays",
            "Trailing3CompleteMonthsSalesQuantity",
            "Prior3CompleteMonthsSalesQuantity",
            "DemandHistoryAvailableFlag",
            "DemandTrendHistoryAvailableFlag",
            "RecentDailySalesVelocity",
            "PriorDailySalesVelocity",
            "DemandTrendPct",
            "OnHandCoverageDays",
            "AvailableCoverageDays",
            "ReorderExceptionFlag",
            "ExpiredInventoryFlag",
            "ZeroOnHandFlag",
            "PositiveInTransitFlag",
            "NoRecentDemandFlag",
            "ZeroOnHandWithRecentDemandFlag",
            "LowOnHandCoverageFlag",
            "VeryLowOnHandCoverageFlag",
            "LowAvailableCoverageFlag",
            "DemandIncreasingFlag",
            "DemandDecliningFlag",
            "CoveragePressureScore",
            "CoveragePressureLevel",
            "LowCoveragePressureFlag",
            "ExcessSlowMovingScore",
            "ExcessSlowMovingLevel",
            "ExcessSlowMovingFlag",
            "PrimaryInventoryRiskDriver",
            "ModelOrRuleVersion",
            "RunDate",
        ]
        output = frame[output_columns].copy()
        output["SnapshotDate"] = pd.to_datetime(output["SnapshotDate"]).dt.date
        for quantity_column in (
            "Trailing3CompleteMonthsSalesQuantity",
            "Prior3CompleteMonthsSalesQuantity",
        ):
            output[quantity_column] = output[quantity_column].astype("int64")
        keys = ["SnapshotDate", "DistributorID", "ProductID", "ModelOrRuleVersion"]
        if output[keys].isna().any(axis=None):
            raise ValueError("Inventory intelligence output contains null grain keys.")
        if output.duplicated(keys).any():
            raise ValueError("Inventory intelligence output has duplicate grain keys.")
        if output["PrimaryInventoryRiskDriver"].isna().any():
            raise ValueError("Primary inventory driver is incomplete.")
        inventory_measures = [
            "OnHandQuantity",
            "InTransitQuantity",
            "AvailableInventoryQty",
            "ReorderPoint",
            "ExpiredQuantity",
            "Trailing3CompleteMonthsSalesQuantity",
            "Prior3CompleteMonthsSalesQuantity",
        ]
        if (output[inventory_measures] < 0).any(axis=None):
            raise ValueError("Inventory quantities, reorder points, or demand are negative.")
        if (
            output["AvailableInventoryQty"]
            != output["OnHandQuantity"] + output["InTransitQuantity"]
        ).any():
            raise ValueError("Available inventory does not equal On Hand plus In Transit.")
        expected_freshness_by_row = output["SnapshotDate"].map(
            lambda snapshot: (args.run_date - snapshot).days
        )
        if not output["SnapshotFreshnessDays"].equals(expected_freshness_by_row):
            raise ValueError("Snapshot freshness does not match run date by snapshot.")
        con.register("inventory_output_input", output)

        coverage_error = (
            output["OnHandCoverageDays"]
            - output["OnHandQuantity"] / output["RecentDailySalesVelocity"]
        ).abs()
        available_error = (
            output["AvailableCoverageDays"]
            - output["AvailableInventoryQty"] / output["RecentDailySalesVelocity"]
        ).abs()
        max_coverage_error = float(
            max(coverage_error.max(skipna=True), available_error.max(skipna=True))
        )
        if max_coverage_error > 1e-9:
            raise ValueError(f"Coverage formula validation failed: {max_coverage_error}.")
        if output.loc[
            output["RecentDailySalesVelocity"].isna(),
            ["OnHandCoverageDays", "AvailableCoverageDays"],
        ].notna().any(axis=None):
            raise ValueError("Coverage is not null when demand velocity is unavailable.")
        if output.loc[
            output["DemandHistoryAvailableFlag"], "NoRecentDemandFlag"
        ].isna().any():
            raise ValueError("Mature recent-demand flags contain null values.")
        expected_recent_velocity = frame["SalesVelocityQuantityPerDay"].where(
            frame["DemandHistoryAvailableFlag"]
            & (frame["SalesVelocityQuantityPerDay"] > 0)
        )
        expected_prior_velocity = (
            frame["Prior3CompleteMonthsSalesQuantity"]
            / (
                (
                    frame["SnapshotDate"].dt.to_period("M").dt.to_timestamp()
                    - pd.DateOffset(months=3)
                )
                - (
                    frame["SnapshotDate"].dt.to_period("M").dt.to_timestamp()
                    - pd.DateOffset(months=6)
                )
            ).dt.days
        ).where(
            frame["DemandTrendHistoryAvailableFlag"]
            & (frame["Prior3CompleteMonthsSalesQuantity"] > 0)
        )
        expected_trend = (
            (
                frame["Trailing3CompleteMonthsSalesQuantity"]
                - frame["Prior3CompleteMonthsSalesQuantity"]
            )
            / frame["Prior3CompleteMonthsSalesQuantity"].replace(0, np.nan)
        ).where(frame["DemandTrendHistoryAvailableFlag"])
        recent_velocity_mismatches = int(
            np.count_nonzero(
                ~np.isclose(
                frame["RecentDailySalesVelocity"].to_numpy(dtype=float, na_value=np.nan),
                expected_recent_velocity.to_numpy(dtype=float, na_value=np.nan),
                rtol=1e-9,
                atol=1e-12,
                equal_nan=True,
                )
            )
        )
        prior_velocity_mismatches = int(
            np.count_nonzero(
                ~np.isclose(
                    frame["PriorDailySalesVelocity"].to_numpy(
                        dtype=float, na_value=np.nan
                    ),
                    expected_prior_velocity.to_numpy(
                        dtype=float, na_value=np.nan
                    ),
                    rtol=1e-9,
                    atol=1e-12,
                    equal_nan=True,
                )
            )
        )
        trend_mismatches = int(
            np.count_nonzero(
                ~np.isclose(
                    expected_trend.to_numpy(dtype=float, na_value=np.nan),
                frame["SourceDemandTrendPct"].where(
                    frame["DemandTrendHistoryAvailableFlag"]
                ).to_numpy(dtype=float, na_value=np.nan),
                rtol=1e-9,
                atol=1e-12,
                equal_nan=True,
                )
            )
        )
        if recent_velocity_mismatches or prior_velocity_mismatches or trend_mismatches:
            raise ValueError(
                "Pre-snapshot velocity/trend formula checks failed: "
                f"recent={recent_velocity_mismatches}, "
                f"prior={prior_velocity_mismatches}, trend={trend_mismatches}"
            )
        if not output["ReorderExceptionFlag"].equals(
            output["OnHandQuantity"] < output["ReorderPoint"]
        ):
            raise ValueError("Reorder exception formula validation failed.")
        if not output["ExpiredInventoryFlag"].equals(output["ExpiredQuantity"] > 0):
            raise ValueError("Expired inventory flag validation failed.")
        expected_freshness = (args.run_date - latest_date.date()).days
        if latest["SnapshotFreshnessDays"].ne(expected_freshness).any():
            raise ValueError(
                "Latest snapshot freshness does not match the run date: "
                f"expected {expected_freshness} days."
            )
        if output["CoveragePressureScore"].min() < 0 or output[
            "CoveragePressureScore"
        ].max() > 100:
            raise ValueError("Coverage-pressure score is outside [0, 100].")
        if output["ExcessSlowMovingScore"].min() < 0 or output[
            "ExcessSlowMovingScore"
        ].max() > 100:
            raise ValueError("Excess/slow-moving score is outside [0, 100].")

        # Reconcile every snapshot separately; no cross-snapshot inventory total is formed.
        reconciliation = con.execute(
            """
            SELECT
                f.SnapshotDate,
                COUNT(*) AS OutputPositions,
                COUNT(DISTINCT (f.DistributorID, f.ProductID)) AS UniqueFactPositions,
                COUNT(*) FILTER (WHERE i.DistributorID IS NULL) AS MissingSourceKeys,
                SUM(f.OnHandQuantity) AS OutputOnHandQty,
                SUM(i.OnHandQty) AS SourceOnHandQty,
                SUM(f.InTransitQuantity) AS OutputInTransitQty,
                SUM(i.InTransitQty) AS SourceInTransitQty,
                SUM(f.ExpiredQuantity) AS OutputExpiredQty,
                SUM(i.ExpiredQty) AS SourceExpiredQty,
                SUM(f.ReorderPoint) AS OutputReorderPointTotal,
                SUM(i.ReorderPoint) AS SourceReorderPointTotal,
                COUNT(*) FILTER (
                    WHERE f.OnHandQuantity IS DISTINCT FROM i.OnHandQty
                       OR f.InTransitQuantity IS DISTINCT FROM i.InTransitQty
                       OR f.ExpiredQuantity IS DISTINCT FROM i.ExpiredQty
                       OR f.ReorderPoint IS DISTINCT FROM i.ReorderPoint
                ) AS MeasureMismatches,
                COUNT(*) FILTER (
                    WHERE f.ReorderExceptionFlag
                       IS DISTINCT FROM (i.OnHandQty < i.ReorderPoint)
                ) AS ReorderFlagMismatches
            FROM inventory_output_input f
            LEFT JOIN analytics.main.fact_inventory i
              USING (SnapshotDate, DistributorID, ProductID)
            GROUP BY f.SnapshotDate
            ORDER BY f.SnapshotDate
            """
        ).fetchdf()
        if reconciliation["MissingSourceKeys"].sum() or reconciliation[
            "MeasureMismatches"
        ].sum() or reconciliation["ReorderFlagMismatches"].sum():
            raise ValueError(
                "Snapshot-level inventory fact reconciliation failed: "
                f"{reconciliation.to_dict('records')}"
            )
        if not (
            reconciliation["OutputPositions"]
            == reconciliation["UniqueFactPositions"]
        ).all():
            raise ValueError("A snapshot contains duplicate distributor-product keys.")
        demand_reconciliation = con.execute(
            """
            WITH monthly_demand AS (
                SELECT
                    DistributorID,
                    ProductID,
                    date_trunc('month', "Date")::DATE AS MonthStart,
                    SUM(Qty) AS SalesQuantity
                FROM analytics.main.vw_sales_analysis
                GROUP BY 1, 2, 3
            ),
            demand_windows AS (
                SELECT
                    f.SnapshotDate,
                    f.DistributorID,
                    f.ProductID,
                    f.Trailing3CompleteMonthsSalesQuantity,
                    f.Prior3CompleteMonthsSalesQuantity,
                    COALESCE(SUM(m.SalesQuantity) FILTER (
                        WHERE m.MonthStart >= date_trunc('month', f.SnapshotDate)
                            - INTERVAL '3 months'
                          AND m.MonthStart < date_trunc('month', f.SnapshotDate)
                    ), 0) AS RecomputedRecent3MonthQty,
                    COALESCE(SUM(m.SalesQuantity) FILTER (
                        WHERE m.MonthStart >= date_trunc('month', f.SnapshotDate)
                            - INTERVAL '6 months'
                          AND m.MonthStart < date_trunc('month', f.SnapshotDate)
                            - INTERVAL '3 months'
                    ), 0) AS RecomputedPrior3MonthQty
                FROM features.main.feature_inventory_risk f
                LEFT JOIN monthly_demand m
                  ON m.DistributorID = f.DistributorID
                 AND m.ProductID = f.ProductID
                 AND m.MonthStart >= date_trunc('month', f.SnapshotDate)
                    - INTERVAL '6 months'
                 AND m.MonthStart < date_trunc('month', f.SnapshotDate)
                GROUP BY 1, 2, 3, 4, 5
            )
            SELECT
                SnapshotDate,
                COUNT(*) AS Positions,
                COUNT(*) FILTER (
                    WHERE Trailing3CompleteMonthsSalesQuantity
                        IS DISTINCT FROM RecomputedRecent3MonthQty
                ) AS RecentDemandMismatches,
                COUNT(*) FILTER (
                    WHERE Prior3CompleteMonthsSalesQuantity
                        IS DISTINCT FROM RecomputedPrior3MonthQty
                ) AS PriorDemandMismatches
            FROM demand_windows
            GROUP BY SnapshotDate
            ORDER BY SnapshotDate
            """
        ).fetchdf()
        if demand_reconciliation[
            ["RecentDemandMismatches", "PriorDemandMismatches"]
        ].to_numpy().sum():
            raise ValueError(
                "Pre-snapshot demand feature reconciliation failed: "
                f"{demand_reconciliation.to_dict('records')}"
            )
        con.unregister("inventory_output_input")

        current_row = distribution.loc[
            distribution["SnapshotDate"] == latest_date.date()
        ].iloc[0]
        current_drivers = (
            latest.groupby("PrimaryInventoryRiskDriver")
            .agg(
                Positions=("ProductID", "size"),
                OnHandQty=("OnHandQuantity", "sum"),
                InTransitQty=("InTransitQuantity", "sum"),
                ExpiredQty=("ExpiredQuantity", "sum"),
                Recent3MonthSalesQuantity=(
                    "Trailing3CompleteMonthsSalesQuantity",
                    "sum",
                ),
            )
            .reset_index()
            .sort_values(["Positions", "PrimaryInventoryRiskDriver"], ascending=[False, True])
        )
        current_summary = {
            "snapshot_date": latest_date.date().isoformat(),
            "positions": int(len(latest)),
            "reorder_exceptions": int(latest["ReorderExceptionFlag"].sum()),
            "zero_on_hand_positions": int(latest["ZeroOnHandFlag"].sum()),
            "expired_inventory_positions": int(latest["ExpiredInventoryFlag"].sum()),
            "expired_quantity": int(latest["ExpiredQuantity"].sum()),
            "no_recent_demand_positions": int(
                latest["NoRecentDemandFlag"].fillna(False).sum()
            ),
            "low_coverage_pressure_positions": int(
                latest["LowCoveragePressureFlag"].sum()
            ),
            "medium_coverage_pressure_positions": int(
                latest["CoveragePressureLevel"].eq("Medium").sum()
            ),
            "high_coverage_pressure_positions": int(
                latest["CoveragePressureLevel"].eq("High").sum()
            ),
            "excess_slow_moving_positions": int(
                latest["ExcessSlowMovingFlag"].sum()
            ),
            "medium_excess_slow_moving_positions": int(
                latest["ExcessSlowMovingLevel"].eq("Medium").sum()
            ),
            "high_excess_slow_moving_positions": int(
                latest["ExcessSlowMovingLevel"].eq("High").sum()
            ),
            "primary_drivers": current_drivers.to_dict("records"),
        }
        summary = {
            "model_version": MODEL_VERSION,
            "run_date": args.run_date.isoformat(),
            "as_of_date": latest_date.date().isoformat(),
            "snapshot_count": int(frame["SnapshotDate"].nunique()),
            "source_position_rows": len(source),
            "output_rows": len(output),
            "first_sales_month": first_sales_month.strftime("%Y-%m"),
            "last_sales_month": max_sales_month.strftime("%Y-%m"),
            "coverage_thresholds": thresholds,
            "threshold_sample_sizes": samples,
            "current_snapshot": current_summary,
            "coverage_threshold_stability": (
                frame.groupby("SnapshotDate")["OnHandCoverageDays"]
                .quantile([0.10, 0.25, 0.50, 0.75, 0.90])
                .unstack()
                .reset_index()
                .rename(
                    columns={
                        0.1: "P10",
                        0.25: "P25",
                        0.5: "P50",
                        0.75: "P75",
                        0.9: "P90",
                    }
                )
                .to_dict("records")
            ),
            "snapshot_reconciliation": reconciliation.to_dict("records"),
            "demand_feature_reconciliation": demand_reconciliation.to_dict(
                "records"
            ),
            "threshold_sensitivity": sensitivity.to_dict("records"),
            "future_demand_association": association.to_dict("records"),
            "limitations": [
                "Coverage and pressure levels are relative analytical screening signals, not service-level or lead-time thresholds.",
                "No stockout probability/date is estimated; lead time, order cadence and complete future purchase orders are unavailable.",
                "No future expiry, shelf-life, lot-level expiry, lost-sales or write-off estimate is produced.",
                "Expired quantity is a current snapshot condition; its high prevalence is preserved from source and does not imply future expiry.",
                "No Recent Demand is set only when the complete prior three-month sales window is observable; earlier rows are marked history-unavailable.",
                "Historical distributor-product demand uses the current customer-to-distributor mapping; mapping changes are not historized.",
                "Future-demand comparisons are descriptive, non-causal, and use overlapping three-month windows.",
            ],
        }

        distribution["ModelOrRuleVersion"] = MODEL_VERSION
        transitions["ModelOrRuleVersion"] = MODEL_VERSION
        sensitivity["ModelOrRuleVersion"] = MODEL_VERSION
        association["ModelOrRuleVersion"] = MODEL_VERSION
        support["ModelOrRuleVersion"] = MODEL_VERSION
        validation_rows = []
        checks = {
            "OutputRows": (len(output), "PASS"),
            "UniqueSnapshotDistributorProductKeys": (
                int(output[keys].drop_duplicates().shape[0]),
                "PASS",
            ),
            "NullGrainKeys": (int(output[keys].isna().any(axis=1).sum()), "PASS"),
            "CoverageFormulaMaxAbsoluteErrorDays": (max_coverage_error, "PASS"),
            "AllSnapshotKeysReconciled": (
                int((reconciliation["MissingSourceKeys"] == 0).all()),
                "PASS",
            ),
            "SnapshotMeasureMismatches": (
                int(reconciliation["MeasureMismatches"].sum()),
                "PASS",
            ),
            "RecentVelocityMismatches": (recent_velocity_mismatches, "PASS"),
            "PriorVelocityMismatches": (prior_velocity_mismatches, "PASS"),
            "DemandTrendMismatches": (trend_mismatches, "PASS"),
            "ReorderFlagMismatches": (
                int(reconciliation["ReorderFlagMismatches"].sum()),
                "PASS",
            ),
            "PreSnapshotDemandWindowMismatches": (
                int(
                    demand_reconciliation[
                        ["RecentDemandMismatches", "PriorDemandMismatches"]
                    ].to_numpy().sum()
                ),
                "PASS",
            ),
            "LatestSnapshotPositions": (len(latest), "PASS"),
            "SnapshotInventoryNotSummedAcrossDates": (
                "One reconciliation row per snapshot; quantities are date-specific",
                "PASS",
            ),
        }
        for name, (value, status) in checks.items():
            validation_rows.append(
                {
                    "Validation": name,
                    "Value": value,
                    "Status": status,
                    "ModelOrRuleVersion": MODEL_VERSION,
                }
            )
        validation_summary = pd.DataFrame(validation_rows)
        exports = {
            "fact_inventory_risk": output,
            "inventory_risk_support_assessment": support,
            "inventory_risk_threshold_config": threshold_table,
            "inventory_risk_validation_summary": validation_summary,
            "inventory_risk_signal_distribution_by_snapshot": distribution,
            "inventory_risk_demand_reconciliation_by_snapshot": demand_reconciliation,
            "inventory_risk_signal_transition_summary": transitions,
            "inventory_risk_threshold_sensitivity": sensitivity,
            "inventory_risk_future_demand_association": association,
        }
        con.execute("BEGIN TRANSACTION")
        for table, data in exports.items():
            registered = f"input_{table}"
            con.register(registered, data)
            con.execute(
                f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM "{registered}"'
            )

        persisted = con.execute(
            """
            SELECT
                COUNT(*),
                COUNT(DISTINCT (SnapshotDate, DistributorID, ProductID, ModelOrRuleVersion)),
                COUNT(*) FILTER (
                    WHERE SnapshotDate IS NULL OR DistributorID IS NULL
                       OR ProductID IS NULL OR ModelOrRuleVersion IS NULL
                ),
                COUNT(*) FILTER (WHERE PrimaryInventoryRiskDriver IS NULL)
            FROM fact_inventory_risk
            """
        ).fetchone()
        expected = (len(output), len(output), 0, 0)
        if persisted != expected:
            raise ValueError(
                f"Persisted inventory grain validation failed: {persisted} != {expected}"
            )

        with tempfile.TemporaryDirectory(
            prefix=".inventory-intelligence-", dir=OUTPUT_DIR
        ) as stage:
            for table in exports:
                path = Path(stage) / f"{table}.csv"
                path_sql = str(path).replace("'", "''")
                con.execute(
                    f'COPY "{table}" TO \'{path_sql}\' '
                    "(HEADER, DELIMITER ',', FORMAT CSV)"
                )
            report_path = Path(stage) / "inventory_intelligence_validation.json"
            report_path.write_text(
                json.dumps(
                    json_safe(summary),
                    indent=2,
                    allow_nan=False,
                    default=str,
                )
                + "\n",
                encoding="utf-8",
            )
            con.execute("COMMIT")
            for table in exports:
                (Path(stage) / f"{table}.csv").replace(
                    OUTPUT_DIR / f"{table}.csv"
                )
            report_path.replace(OUTPUT_DIR / "inventory_intelligence_validation.json")
        summary["persisted_tables"] = list(exports)
        return summary
    except Exception:
        try:
            con.execute("ROLLBACK")
        except duckdb.Error:
            pass
        raise
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-db", type=Path, default=FEATURE_DB)
    parser.add_argument("--analytics-db", type=Path, default=ANALYTICS_DB)
    parser.add_argument("--output-db", type=Path, default=OUTPUT_DB)
    parser.add_argument(
        "--as-of-date", type=date.fromisoformat, default=date(2026, 9, 30)
    )
    parser.add_argument("--run-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(json_safe(result), indent=2, allow_nan=False, default=str))


if __name__ == "__main__":
    main()
