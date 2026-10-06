"""Build explainable customer segments and separate relative-risk scores."""

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
OUTPUT_DB = ROOT / "database" / "fmcg_predictive_outputs.duckdb"
OUTPUT_DIR = ROOT / "processed" / "predictive"
MODEL_VERSION = "fmcg-customer-intelligence-v1.0.0"
CURRENT_AS_OF_MONTH = pd.Timestamp("2026-09-01")
MIN_HISTORY_MONTHS = 6
LABEL_START_MONTH = pd.Timestamp("2025-06-01")
LABEL_END_MONTH = pd.Timestamp("2026-06-01")
DECLINE_TRAIN_END = pd.Timestamp("2025-09-01")
DECLINE_TEST_START = pd.Timestamp("2026-01-01")
DECLINE_TEST_END = pd.Timestamp("2026-06-01")
DECLINE_QUANTILE = 0.25
DECLINE_MINIMUM_MONTHS_BELOW_BASELINE = 2
LOW_RISK_QUANTILE = 0.50
HIGH_RISK_QUANTILE = 0.80
SEGMENT_VERSION = "customer-segment-v1"
RISK_VERSION = "customer-risk-v1"
SEGMENTS = (
    "POTENTIAL",
    "CORE / MAINTAIN",
    "RISK / DECLINING",
    "LOW PRIORITY / DORMANT",
    "INSUFFICIENT HISTORY",
)
COMPONENTS = ("ValueScore", "MomentumScore", "EngagementScore", "CommercialQualityScore")


def percentile_rank(values: pd.Series, higher_is_better: bool = True) -> pd.Series:
    ranks = values.rank(method="average", pct=True)
    ranks = ranks.where(values.notna(), np.nan)
    return 100.0 * (ranks if higher_is_better else 1.0 - ranks)


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


def finite_mean(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    return frame[columns].replace([np.inf, -np.inf], np.nan).mean(axis=1, skipna=True)


def load_and_score(
    con: duckdb.DuckDBPyConnection, feature_db: Path
) -> pd.DataFrame:
    feature_path = str(feature_db.resolve()).replace("'", "''")
    con.execute(f"ATTACH '{feature_path}' AS features (READ_ONLY)")
    result = con.execute(
        "SELECT * FROM features.main.feature_customer_monthly "
        "ORDER BY CustomerID, AsOfMonth"
    ).fetchdf()
    if result.empty:
        raise ValueError("Validated customer-month feature table is empty.")
    keys = ["CustomerID", "AsOfMonth"]
    if result[keys].isna().any(axis=None):
        raise ValueError("Customer feature keys contain null values.")
    if result.duplicated(keys).any():
        raise ValueError("Customer feature table is not unique at Customer × AsOfMonth.")
    if result["AsOfMonth"].max() != CURRENT_AS_OF_MONTH:
        raise ValueError(
            f"Unexpected feature cutoff: {result['AsOfMonth'].max()}."
        )

    result["HistoryMonths"] = result.groupby("CustomerID").cumcount() + 1
    result["Prior3ActiveMonths"] = (
        result.groupby("CustomerID", sort=False)["ActiveMonth"]
        .transform(lambda values: values.shift(3).rolling(3, min_periods=3).sum())
    )
    result["ActiveMonthTrend"] = (
        result["ActiveMonthsTrailing3"] - result["Prior3ActiveMonths"]
    )
    grouped = result.groupby("CustomerID", sort=False)
    for source, target in [
        ("GrossMargin", "Trailing12MonthGrossMargin"),
        ("DiscountAmount", "Trailing12MonthDiscountAmount"),
        ("ReturnAmount", "Trailing12MonthReturnAmount"),
    ]:
        result[target] = grouped[source].transform(
            lambda values: values.rolling(12, min_periods=1).sum()
        )
    result["Trailing12MonthGrossSales"] = (
        grouped["NetSales"].transform(
            lambda values: values.rolling(12, min_periods=1).sum()
        )
        + result["Trailing12MonthDiscountAmount"]
    )
    result["Trailing12MonthGrossMarginPct"] = (
        result["Trailing12MonthGrossMargin"]
        / result["Trailing12MonthSales"].replace(0, np.nan)
    )
    result["Trailing12MonthDiscountPct"] = (
        result["Trailing12MonthDiscountAmount"]
        / result["Trailing12MonthGrossSales"].replace(0, np.nan)
    )
    result["Trailing12MonthReturnRate"] = (
        result["Trailing12MonthReturnAmount"]
        / result["Trailing12MonthSales"].replace(0, np.nan)
    )
    result["RecencyCadenceRatio"] = (
        result["DaysSinceLastPurchase"]
        / result["AveragePurchaseIntervalDaysTrailing12"].replace(0, np.nan)
    )

    eligible = result["HistoryMonths"] >= MIN_HISTORY_MONTHS
    cohort = result.loc[eligible].copy()
    if cohort.empty:
        raise ValueError("No customer-as-of observations meet minimum history.")

    cohort["RankSalesValue"] = cohort.groupby("AsOfMonth")[
        "Trailing12MonthSales"
    ].transform(percentile_rank)
    cohort["RankMarginValue"] = cohort.groupby("AsOfMonth")[
        "Trailing12MonthGrossMargin"
    ].transform(percentile_rank)
    cohort["RankSalesPerActiveMonth"] = cohort.groupby("AsOfMonth")[
        "SalesPerActiveMonthTrailing12"
    ].transform(percentile_rank)
    cohort["ValueScore"] = finite_mean(
        cohort,
        ["RankSalesValue", "RankMarginValue", "RankSalesPerActiveMonth"],
    )

    cohort["RankSalesMomentum"] = cohort.groupby("AsOfMonth")[
        "RecentSalesTrendPct"
    ].transform(percentile_rank)
    cohort["RankQuantityMomentum"] = cohort.groupby("AsOfMonth")[
        "RecentQuantityTrendPct"
    ].transform(percentile_rank)
    cohort["RankActivityMomentum"] = cohort.groupby("AsOfMonth")[
        "ActiveMonthTrend"
    ].transform(percentile_rank)
    cohort["MomentumScore"] = finite_mean(
        cohort,
        ["RankSalesMomentum", "RankQuantityMomentum", "RankActivityMomentum"],
    )

    cohort["RankRecencyEngagement"] = cohort.groupby("AsOfMonth")[
        "RecencyCadenceRatio"
    ].transform(lambda values: percentile_rank(values, higher_is_better=False))
    cohort["RankFrequencyEngagement"] = cohort.groupby("AsOfMonth")[
        "PurchaseFrequencyTrailing3Months"
    ].transform(percentile_rank)
    cohort["RankConsistencyEngagement"] = cohort.groupby("AsOfMonth")[
        "PurchaseConsistencyTrailing6"
    ].transform(percentile_rank)
    cohort["RankActiveMonthsEngagement"] = cohort.groupby("AsOfMonth")[
        "ActiveMonthsTrailing6"
    ].transform(percentile_rank)
    cohort["EngagementScore"] = finite_mean(
        cohort,
        [
            "RankRecencyEngagement",
            "RankFrequencyEngagement",
            "RankConsistencyEngagement",
            "RankActiveMonthsEngagement",
        ],
    )

    cohort["RankMarginQuality"] = cohort.groupby("AsOfMonth")[
        "Trailing12MonthGrossMarginPct"
    ].transform(percentile_rank)
    cohort["RankDiscountQuality"] = cohort.groupby("AsOfMonth")[
        "Trailing12MonthDiscountPct"
    ].transform(lambda values: percentile_rank(values, higher_is_better=False))
    cohort["RankReturnQuality"] = cohort.groupby("AsOfMonth")[
        "Trailing12MonthReturnRate"
    ].transform(lambda values: percentile_rank(values, higher_is_better=False))
    cohort["CommercialQualityScore"] = finite_mean(
        cohort, ["RankMarginQuality", "RankDiscountQuality", "RankReturnQuality"]
    )

    cohort["DeclineSignalSales"] = percentile_rank(
        cohort["RecentSalesTrendPct"], higher_is_better=False
    )
    cohort["DeclineSignalQuantity"] = percentile_rank(
        cohort["RecentQuantityTrendPct"], higher_is_better=False
    )
    cohort["DeclineSignalActivity"] = percentile_rank(
        cohort["ActiveMonthTrend"], higher_is_better=False
    )
    cohort["DeclineRiskScore"] = finite_mean(
        cohort,
        [
            "DeclineSignalSales",
            "DeclineSignalQuantity",
            "DeclineSignalActivity",
        ],
    )

    cohort["InactivitySignalRecency"] = percentile_rank(
        cohort["RecencyCadenceRatio"], higher_is_better=True
    )
    cohort["InactivitySignalFrequency"] = percentile_rank(
        cohort["PurchaseFrequencyTrailing3Months"], higher_is_better=False
    )
    cohort["InactivitySignalConsistency"] = percentile_rank(
        cohort["PurchaseConsistencyTrailing6"], higher_is_better=False
    )
    cohort["InactivitySignalActiveMonths"] = percentile_rank(
        cohort["ActiveMonthsTrailing6"], higher_is_better=False
    )
    cohort["InactivityRiskScore"] = finite_mean(
        cohort,
        [
            "InactivitySignalRecency",
            "InactivitySignalFrequency",
            "InactivitySignalConsistency",
            "InactivitySignalActiveMonths",
        ],
    )
    cohort["InactivityRiskEligible"] = (
        cohort["AveragePurchaseIntervalDaysTrailing12"].notna()
        & cohort["RecencyCadenceRatio"].notna()
        & cohort["InactivityRiskScore"].notna()
    )
    cohort.loc[~cohort["InactivityRiskEligible"], "InactivityRiskScore"] = np.nan
    result = result.merge(
        cohort[
            [
                "CustomerID",
                "AsOfMonth",
                *COMPONENTS,
                "DeclineRiskScore",
                "InactivityRiskScore",
                "InactivityRiskEligible",
                "DeclineSignalSales",
                "DeclineSignalQuantity",
                "DeclineSignalActivity",
                "InactivitySignalRecency",
                "InactivitySignalFrequency",
                "InactivitySignalConsistency",
                "InactivitySignalActiveMonths",
            ]
        ],
        on=["CustomerID", "AsOfMonth"],
        how="left",
        validate="one_to_one",
    )
    result["InactivityRiskEligible"] = (
        result["InactivityRiskEligible"].fillna(False).astype(bool)
    )
    return result


def assign_segments(frame: pd.DataFrame, offsets: dict[str, float] | None = None) -> pd.DataFrame:
    offsets = offsets or {}
    current = frame.loc[frame["HistoryMonths"] >= MIN_HISTORY_MONTHS].copy()
    thresholds = current.groupby("AsOfMonth").agg(
        ValueP50=("ValueScore", lambda x: x.quantile(0.50)),
        MomentumP30=("MomentumScore", lambda x: x.quantile(0.30)),
        MomentumP70=("MomentumScore", lambda x: x.quantile(0.70)),
        EngagementP30=("EngagementScore", lambda x: x.quantile(0.30)),
        EngagementP50=("EngagementScore", lambda x: x.quantile(0.50)),
    )
    for name, shift in (offsets or {}).items():
        thresholds[name] += shift
    current = current.join(thresholds, on="AsOfMonth")
    meaningful_value = current["ValueScore"] >= current["ValueP50"]
    sustained_deterioration = (
        (current["MomentumScore"] <= current["MomentumP30"])
        | (
            (current["EngagementScore"] <= current["EngagementP30"])
            & (current["ActiveMonthTrend"] < 0)
        )
    )
    potential = (
        (current["MomentumScore"] >= current["MomentumP70"])
        & (current["EngagementScore"] >= current["EngagementP50"])
    )
    current["CommercialSegment"] = np.select(
        [
            meaningful_value & sustained_deterioration,
            meaningful_value,
            potential,
        ],
        [
            "RISK / DECLINING",
            "CORE / MAINTAIN",
            "POTENTIAL",
        ],
        default="LOW PRIORITY / DORMANT",
    )
    current["SegmentValueP50"] = current["ValueP50"]
    current["SegmentMomentumP30"] = current["MomentumP30"]
    current["SegmentMomentumP70"] = current["MomentumP70"]
    current["SegmentEngagementP30"] = current["EngagementP30"]
    current["SegmentEngagementP50"] = current["EngagementP50"]
    assigned = frame.drop(columns=["CommercialSegment"], errors="ignore").merge(
        current[
            [
                "CustomerID",
                "AsOfMonth",
                "CommercialSegment",
                "SegmentValueP50",
                "SegmentMomentumP30",
                "SegmentMomentumP70",
                "SegmentEngagementP30",
                "SegmentEngagementP50",
            ]
        ],
        on=["CustomerID", "AsOfMonth"],
        how="left",
        validate="one_to_one",
    ).assign(
        SegmentCandidate=lambda x: x["CommercialSegment"].fillna(
            "INSUFFICIENT HISTORY"
        )
    )
    assigned = assigned.sort_values(["CustomerID", "AsOfMonth"]).copy()

    def confirm_candidate(group: pd.DataFrame) -> pd.Series:
        candidates = group["SegmentCandidate"].tolist()
        output: list[str] = []
        confirmed_segments = {"RISK / DECLINING", "POTENTIAL"}
        for index, candidate in enumerate(candidates):
            if candidate == "INSUFFICIENT HISTORY":
                output.append(candidate)
            elif index == 0 or output[-1] == "INSUFFICIENT HISTORY":
                output.append(candidate)
            elif candidate == output[-1]:
                output.append(candidate)
            elif (
                candidate in confirmed_segments
                and index > 0
                and candidate == candidates[index - 1]
            ):
                output.append(candidate)
            elif candidate in confirmed_segments:
                output.append(output[-1])
            else:
                output.append(candidate)
        return pd.Series(output, index=group.index)

    assigned["CommercialSegment"] = assigned.groupby(
        "CustomerID", sort=False, group_keys=False
    ).apply(confirm_candidate, include_groups=False)
    return assigned.drop(columns=["SegmentCandidate"])


def build_outcomes(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.sort_values(["CustomerID", "AsOfMonth"]).copy()
    grouped = ordered.groupby("CustomerID", sort=False)
    for periods, suffix in ((1, "1"), (2, "2"), (3, "3")):
        ordered[f"FutureSales{suffix}"] = grouped["NetSales"].shift(-periods)
        ordered[f"FutureTransactions{suffix}"] = grouped["TransactionCount"].shift(
            -periods
        )
        ordered[f"FutureActiveMonth{suffix}"] = grouped["ActiveMonth"].shift(
            -periods
        )
        ordered[f"FutureAsOfDate{suffix}"] = grouped["AsOfDate"].shift(-periods)
        ordered[f"FutureLastPurchase{suffix}"] = grouped["LastPurchaseDate"].shift(
            -periods
        )
    ordered["FutureSales3Month"] = ordered[
        ["FutureSales1", "FutureSales2", "FutureSales3"]
    ].sum(axis=1, min_count=3)
    ordered["FutureTransactions3Month"] = ordered[
        ["FutureTransactions1", "FutureTransactions2", "FutureTransactions3"]
    ].sum(axis=1, min_count=3)
    ordered["FutureActiveMonths3"] = ordered[
        ["FutureActiveMonth1", "FutureActiveMonth2", "FutureActiveMonth3"]
    ].sum(axis=1, min_count=3)
    ordered["FutureMonthsBelowSalesBaseline"] = sum(
        (ordered[f"FutureSales{i}"] < ordered["Trailing3MonthSalesAverage"])
        .fillna(False)
        .astype(int)
        for i in ("1", "2", "3")
    )
    ordered["FutureWindowEnd"] = ordered["FutureAsOfDate3"]
    ordered["FutureLastPurchaseDate"] = ordered["FutureLastPurchase3"]
    ordered["ExpectedFutureSales"] = 3 * ordered["Trailing3MonthSalesAverage"]
    ordered["FutureSalesToBaselineRatio"] = (
        ordered["FutureSales3Month"]
        / ordered["ExpectedFutureSales"].replace(0, np.nan)
    )
    ordered["FutureGapDays"] = (
        ordered["FutureWindowEnd"] - ordered["FutureLastPurchaseDate"]
    ).dt.days
    eligible = (
        (ordered["HistoryMonths"] >= MIN_HISTORY_MONTHS)
        & ordered["AsOfMonth"].between(LABEL_START_MONTH, LABEL_END_MONTH)
        & ordered["FutureMonthsBelowSalesBaseline"].notna()
        & ordered["FutureSales3Month"].notna()
    )
    outcomes = ordered.loc[eligible].copy()
    outcomes["DeclineLabel"] = False
    outcomes["InactivityLabel"] = False
    outcomes["DeclineOutcomeEligible"] = (
        outcomes["FutureSalesToBaselineRatio"].notna()
        & (outcomes["ExpectedFutureSales"] > 0)
    )
    outcomes["InactivityOutcomeEligible"] = (
        outcomes["AveragePurchaseIntervalDaysTrailing12"].notna()
        & outcomes["FutureTransactions3Month"].notna()
        & outcomes["FutureGapDays"].notna()
    )
    outcomes["InactivityLabel"] = (
        outcomes["InactivityOutcomeEligible"]
        & (outcomes["FutureTransactions3Month"] == 0)
        & (
            outcomes["FutureGapDays"]
            > outcomes["AveragePurchaseIntervalDaysTrailing12"]
        )
    )
    return outcomes


def risk_level(score: pd.Series, low_cutoff: float, high_cutoff: float) -> pd.Series:
    return pd.Series(
        np.select(
            [score >= high_cutoff, score <= low_cutoff],
            ["High", "Low"],
            default="Medium",
        ),
        index=score.index,
        dtype="object",
    ).where(score.notna(), None)


def best_youden_threshold(scores: pd.Series, labels: pd.Series, minimum: float) -> tuple[float, float]:
    data = pd.DataFrame({"score": scores, "label": labels}).dropna()
    y = data["label"].astype(bool).to_numpy()
    if y.sum() == 0 or y.sum() == len(y):
        return float("nan"), float("nan")
    candidates = np.unique(data.loc[data["score"] >= minimum, "score"].to_numpy())
    best = (float("nan"), -float("inf"))
    for cutoff in candidates:
        predicted = data["score"].to_numpy() >= cutoff
        tp = np.count_nonzero(predicted & y)
        fp = np.count_nonzero(predicted & ~y)
        tpr = tp / np.count_nonzero(y)
        fpr = fp / np.count_nonzero(~y)
        youden = tpr - fpr
        if youden > best[1]:
            best = (float(cutoff), float(youden))
    return best


def binary_metrics(records: pd.DataFrame, score_name: str, level_name: str) -> dict[str, Any]:
    observed = records.dropna(subset=["Outcome"]).copy()
    observed["Outcome"] = observed["Outcome"].astype(bool)
    overall = float(observed["Outcome"].mean()) if len(observed) else None
    high = observed[observed[level_name] == "High"]
    high_rate = float(high["Outcome"].mean()) if len(high) else None
    positives = int(observed["Outcome"].sum())
    captured = int(high["Outcome"].sum()) if len(high) else 0
    score = observed[score_name].astype(float).to_numpy()
    label = observed["Outcome"].to_numpy(dtype=bool)
    auc = None
    average_precision = None
    if positives and positives < len(observed):
        ranks = pd.Series(score).rank(method="average").to_numpy()
        auc = float(
            (
                ranks[label].sum()
                - positives * (positives + 1) / 2
            )
            / (positives * (len(observed) - positives))
        )
        order = np.argsort(-score)
        sorted_labels = label[order]
        cumulative_tp = np.cumsum(sorted_labels)
        precision = cumulative_tp / np.arange(1, len(sorted_labels) + 1)
        average_precision = float(precision[sorted_labels].sum() / positives)
    levels = {
        level: int((observed[level_name] == level).sum())
        for level in ("Low", "Medium", "High")
    }
    return {
        "observations": len(observed),
        "customers": int(observed["CustomerID"].nunique()),
        "outcomes": positives,
        "overall_outcome_rate": overall,
        "high_risk_customers": int(len(high)),
        "high_risk_outcomes": captured,
        "high_risk_outcome_rate": high_rate,
        "high_risk_lift": high_rate / overall if high_rate is not None and overall else None,
        "high_risk_capture_recall": captured / positives if positives else None,
        "risk_level_counts": levels,
        "roc_auc": auc,
        "average_precision": average_precision,
    }


def auc_score(scores: pd.Series, labels: pd.Series) -> float | None:
    data = pd.DataFrame({"score": scores, "label": labels}).dropna()
    y = data["label"].astype(bool).to_numpy()
    positives = int(y.sum())
    negatives = len(y) - positives
    if positives == 0 or negatives == 0:
        return None
    ranks = data["score"].rank(method="average").to_numpy()
    return float(
        (ranks[y].sum() - positives * (positives + 1) / 2)
        / (positives * negatives)
    )


def driver_for_row(row: pd.Series) -> str:
    if row["HistoryMonths"] < MIN_HISTORY_MONTHS:
        return "Insufficient history"
    candidates: list[tuple[float, str]] = []
    if pd.notna(row.get("DeclineRiskScore")):
        for key, label in (
            (
                "DeclineRiskSignalSales",
                "Recent sales trend associated with below-baseline outcomes",
            ),
            (
                "DeclineRiskSignalQuantity",
                "Recent quantity trend associated with below-baseline outcomes",
            ),
            (
                "DeclineRiskSignalActivity",
                "Recent active-month change associated with below-baseline outcomes",
            ),
        ):
            value = row.get(key)
            if pd.notna(value):
                candidates.append((float(value), label))
    if pd.notna(row.get("InactivityRiskScore")):
        for key, label in (
            ("InactivitySignalRecency", "Recency elevated vs purchase cadence"),
            ("InactivitySignalFrequency", "Reduced recent purchase frequency"),
            ("InactivitySignalConsistency", "Lower purchase consistency"),
            ("InactivitySignalActiveMonths", "Fewer active months"),
        ):
            value = row.get(key)
            if pd.notna(value):
                candidates.append((float(value), label))
    return max(candidates, default=(0.0, "No material adverse signal"))[1]


def summarize_segments(frame: pd.DataFrame) -> pd.DataFrame:
    current = frame.loc[frame["AsOfMonth"] == CURRENT_AS_OF_MONTH].copy()
    summary = (
        current.groupby("CommercialSegment", dropna=False)
        .agg(
            Customers=("CustomerID", "nunique"),
            TrailingSales=("Trailing12MonthSales", "sum"),
            TrailingGrossMargin=("Trailing12MonthGrossMargin", "sum"),
            MeanValueScore=("ValueScore", "mean"),
            MeanMomentumScore=("MomentumScore", "mean"),
            MeanEngagementScore=("EngagementScore", "mean"),
            MeanCommercialQualityScore=("CommercialQualityScore", "mean"),
            MedianTrailingSales=("Trailing12MonthSales", "median"),
            MedianActiveMonths6=("ActiveMonthsTrailing6", "median"),
            MedianDaysSinceLastPurchase=("DaysSinceLastPurchase", "median"),
        )
        .reset_index()
    )
    all_customers = max(int(current["CustomerID"].nunique()), 1)
    summary["PopulationPct"] = summary["Customers"] / all_customers
    total_sales = float(summary["TrailingSales"].sum())
    total_margin = float(summary["TrailingGrossMargin"].sum())
    summary["SalesContributionPct"] = summary["TrailingSales"] / total_sales
    summary["GrossMarginContributionPct"] = (
        summary["TrailingGrossMargin"] / total_margin if total_margin else np.nan
    )
    category_order = {segment: i for i, segment in enumerate(SEGMENTS)}
    summary["_order"] = summary["CommercialSegment"].map(category_order)
    return summary.sort_values("_order").drop(columns="_order").reset_index(drop=True)


def transitions(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = frame.sort_values(["CustomerID", "AsOfMonth"]).copy()
    ordered["PreviousSegment"] = ordered.groupby("CustomerID")[
        "CommercialSegment"
    ].shift(1)
    ordered["PreviousMonth"] = ordered.groupby("CustomerID")["AsOfMonth"].shift(1)
    consecutive = ordered[
        (ordered["PreviousMonth"] + pd.offsets.MonthBegin(1) == ordered["AsOfMonth"])
    ].copy()
    month = (
        consecutive.groupby(
            ["PreviousMonth", "AsOfMonth", "PreviousSegment", "CommercialSegment"]
        )
        .size()
        .rename("Customers")
        .reset_index()
    )
    matrix = (
        consecutive.groupby(["PreviousSegment", "CommercialSegment"])
        .size()
        .rename("Transitions")
        .reset_index()
    )
    row_totals = matrix.groupby("PreviousSegment")["Transitions"].transform("sum")
    matrix["TransitionPctOfOrigin"] = matrix["Transitions"] / row_totals
    matrix["Intervals"] = int(consecutive[["PreviousMonth", "AsOfMonth"]].drop_duplicates().shape[0])
    stable = (
        consecutive["PreviousSegment"] == consecutive["CommercialSegment"]
    ).mean()
    mature = consecutive[
        (consecutive["PreviousSegment"] != "INSUFFICIENT HISTORY")
        & (consecutive["CommercialSegment"] != "INSUFFICIENT HISTORY")
    ]
    mature_stable = (
        (mature["PreviousSegment"] == mature["CommercialSegment"]).mean()
        if len(mature)
        else None
    )
    matrix.attrs["stability"] = float(stable) if len(consecutive) else None
    matrix.attrs["mature_stability"] = (
        float(mature_stable) if mature_stable is not None else None
    )
    matrix.attrs["mature_transition_observations"] = len(mature)
    matrix.attrs["transition_observations"] = len(consecutive)
    return matrix, month


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.feature_db.is_file():
        raise FileNotFoundError(f"Customer feature database missing: {args.feature_db}")
    if args.as_of_date != date(2026, 9, 30):
        raise ValueError("Build 3 is scoped to AsOfDate 2026-09-30.")
    if args.output_db.resolve() == args.feature_db.resolve():
        raise ValueError("Output database must not overwrite the feature database.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.output_db))
    try:
        scored = load_and_score(con, args.feature_db)
        if scored["AsOfMonth"].max() != CURRENT_AS_OF_MONTH:
            raise ValueError("Unexpected current as-of month.")

        segment_frame = assign_segments(scored)
        outcomes = build_outcomes(segment_frame)
        threshold_train = outcomes.loc[
            (outcomes["AsOfMonth"] <= DECLINE_TRAIN_END)
            & outcomes["DeclineOutcomeEligible"]
        ]
        if threshold_train.empty:
            raise ValueError("No decline outcome development observations.")
        decline_ratio_threshold = float(
            threshold_train["FutureSalesToBaselineRatio"].quantile(
                DECLINE_QUANTILE
            )
        )
        outcomes["DeclineLabel"] = (
            outcomes["DeclineOutcomeEligible"]
            & (outcomes["FutureSalesToBaselineRatio"] <= decline_ratio_threshold)
            & (
                outcomes["FutureMonthsBelowSalesBaseline"]
                >= DECLINE_MINIMUM_MONTHS_BELOW_BASELINE
            )
        )

        direction_training = outcomes.loc[
            (outcomes["AsOfMonth"] <= DECLINE_TRAIN_END)
            & outcomes["DeclineOutcomeEligible"]
            & outcomes["DeclineRiskScore"].notna()
        ]
        raw_direction_auc = auc_score(
            direction_training["DeclineRiskScore"],
            direction_training["DeclineLabel"],
        )
        decline_score_inverted = (
            raw_direction_auc is not None and raw_direction_auc < 0.5
        )
        if decline_score_inverted:
            for data in (segment_frame, outcomes):
                data["DeclineRiskScore"] = 100 - data["DeclineRiskScore"]
                for signal in (
                    "DeclineSignalSales",
                    "DeclineSignalQuantity",
                    "DeclineSignalActivity",
                ):
                    data[f"DeclineRiskSignal{signal.removeprefix('DeclineSignal')}"] = (
                        100 - data[signal]
                    )
        else:
            for data in (segment_frame, outcomes):
                for signal in (
                    "DeclineSignalSales",
                    "DeclineSignalQuantity",
                    "DeclineSignalActivity",
                ):
                    data[f"DeclineRiskSignal{signal.removeprefix('DeclineSignal')}"] = data[
                        signal
                    ]

        development = outcomes.loc[
            (outcomes["AsOfMonth"] <= DECLINE_TRAIN_END)
            & outcomes["DeclineOutcomeEligible"]
            & outcomes["DeclineRiskScore"].notna()
        ]
        validation = outcomes.loc[
            outcomes["AsOfMonth"].between(DECLINE_TEST_START, DECLINE_TEST_END)
            & outcomes["DeclineOutcomeEligible"]
            & outcomes["DeclineRiskScore"].notna()
        ]
        if development.empty or validation.empty:
            raise ValueError("Decline development or temporal validation set is empty.")
        low_decline_cutoff = float(
            development["DeclineRiskScore"].quantile(LOW_RISK_QUANTILE)
        )
        high_decline_cutoff = float(
            development["DeclineRiskScore"].quantile(
                HIGH_RISK_QUANTILE
            )
        )
        youden_cutoff, youden = best_youden_threshold(
            development["DeclineRiskScore"],
            development["DeclineLabel"],
            low_decline_cutoff,
        )
        decline_threshold_method = (
            "training-score 80th percentile; fixed relative top-quintile tier, "
            "then assessed on temporal holdout"
        )

        inactivity_development = outcomes.loc[
            (outcomes["AsOfMonth"] <= DECLINE_TRAIN_END)
            & outcomes["InactivityOutcomeEligible"]
            & outcomes["InactivityRiskScore"].notna()
        ]
        low_inactivity_cutoff = float(
            inactivity_development["InactivityRiskScore"].quantile(
                LOW_RISK_QUANTILE
            )
        )
        inactivity_label_events = int(inactivity_development["InactivityLabel"].sum())
        if inactivity_label_events:
            high_inactivity_cutoff, inactivity_youden = best_youden_threshold(
                inactivity_development["InactivityRiskScore"],
                inactivity_development["InactivityLabel"],
                low_inactivity_cutoff,
            )
            inactivity_threshold_method = "training Youden J"
        else:
            high_inactivity_cutoff = float(
                inactivity_development["InactivityRiskScore"].quantile(
                    HIGH_RISK_QUANTILE
                )
            )
            inactivity_youden = None
            inactivity_threshold_method = (
                "provisional training-score 80th percentile; no positive "
                "inactivity outcomes were observed"
            )

        segment_frame["DeclineRiskLevel"] = risk_level(
            segment_frame["DeclineRiskScore"],
            low_decline_cutoff,
            high_decline_cutoff,
        )
        segment_frame["InactivityRiskLevel"] = risk_level(
            segment_frame["InactivityRiskScore"],
            low_inactivity_cutoff,
            high_inactivity_cutoff,
        )
        segment_frame["PrimaryRiskDriver"] = segment_frame.apply(
            driver_for_row, axis=1
        )
        segment_frame["PortfolioState"] = (
            segment_frame["CommercialSegment"].astype(str)
            + " + "
            + segment_frame["DeclineRiskLevel"].fillna("Unscored").astype(str)
            + " DECLINE / "
            + segment_frame["InactivityRiskLevel"].fillna("Unscored").astype(str)
            + " INACTIVITY"
        )

        decline_results = outcomes.copy()
        decline_results["RiskLevel"] = risk_level(
            decline_results["DeclineRiskScore"],
            low_decline_cutoff,
            high_decline_cutoff,
        )
        decline_results["Outcome"] = decline_results["DeclineLabel"].astype(float)
        inactivity_results = outcomes.copy()
        inactivity_results["RiskLevel"] = risk_level(
            inactivity_results["InactivityRiskScore"],
            low_inactivity_cutoff,
            high_inactivity_cutoff,
        )
        inactivity_results["Outcome"] = inactivity_results["InactivityLabel"].where(
            inactivity_results["InactivityOutcomeEligible"], np.nan
        )

        validation_rows: list[dict[str, Any]] = []
        for risk_type, records, score_name in (
            ("Decline", decline_results, "DeclineRiskScore"),
            ("Inactivity", inactivity_results, "InactivityRiskScore"),
        ):
            for split, mask in (
                (
                    "Development",
                    records["AsOfMonth"].between(LABEL_START_MONTH, DECLINE_TRAIN_END),
                ),
                (
                    "Temporal holdout",
                    records["AsOfMonth"].between(DECLINE_TEST_START, DECLINE_TEST_END),
                ),
            ):
                summary = binary_metrics(records.loc[mask], score_name, "RiskLevel")
                validation_rows.append(
                    {"RiskType": risk_type, "ValidationSplit": split, **summary}
                )
        risk_validation = pd.DataFrame(validation_rows)

        segment_validation = summarize_segments(segment_frame)
        transition_matrix, transition_by_month = transitions(segment_frame)
        stability = transition_matrix.attrs.get("stability")
        transition_count = transition_matrix.attrs.get("transition_observations", 0)
        mature_stability = transition_matrix.attrs.get("mature_stability")
        mature_transition_count = transition_matrix.attrs.get(
            "mature_transition_observations", 0
        )

        latest = segment_frame.loc[
            segment_frame["AsOfMonth"] == CURRENT_AS_OF_MONTH
        ].copy()
        if latest["CustomerID"].nunique() != 6500:
            raise ValueError(
                f"Current snapshot does not contain all customers: "
                f"{latest['CustomerID'].nunique()}."
            )
        segment_counts = {
            segment: int((latest["CommercialSegment"] == segment).sum())
            for segment in SEGMENTS
        }
        high_decline = latest[latest["DeclineRiskLevel"] == "High"]
        high_inactivity = latest[latest["InactivityRiskLevel"] == "High"]
        overlap_customers = set(high_decline["CustomerID"]) & set(
            high_inactivity["CustomerID"]
        )

        current_risk_groups = (
            latest.groupby(
                ["CommercialSegment", "DeclineRiskLevel", "InactivityRiskLevel"],
                dropna=False,
            )
            .agg(
                Customers=("CustomerID", "nunique"),
                TrailingSales=("Trailing12MonthSales", "sum"),
                TrailingGrossMargin=("Trailing12MonthGrossMargin", "sum"),
                MeanDeclineRiskScore=("DeclineRiskScore", "mean"),
                MeanInactivityRiskScore=("InactivityRiskScore", "mean"),
            )
            .reset_index()
        )
        current_primary_drivers = (
            latest.groupby("PrimaryRiskDriver")
            .agg(
                Customers=("CustomerID", "nunique"),
                TrailingSales=("Trailing12MonthSales", "sum"),
                TrailingGrossMargin=("Trailing12MonthGrossMargin", "sum"),
            )
            .reset_index()
            .sort_values(["Customers", "PrimaryRiskDriver"], ascending=[False, True])
        )

        sensitivity_rows = []
        for name, shifts in (
            ("Base", {}),
            ("Conservative boundaries (+5 points)", {
                "ValueP50": 5,
                "MomentumP30": -5,
                "MomentumP70": 5,
                "EngagementP30": -5,
                "EngagementP50": 5,
            }),
            ("Broader boundaries (-5 points)", {
                "ValueP50": -5,
                "MomentumP30": 5,
                "MomentumP70": -5,
                "EngagementP30": 5,
                "EngagementP50": -5,
            }),
        ):
            alternative = assign_segments(scored, shifts)
            candidate = alternative.loc[
                alternative["AsOfMonth"] == CURRENT_AS_OF_MONTH,
                ["CustomerID", "CommercialSegment"],
            ].rename(columns={"CommercialSegment": "SensitivitySegment"})
            comparison = latest[["CustomerID", "CommercialSegment"]].merge(
                candidate, on="CustomerID", validate="one_to_one"
            )
            sensitivity_rows.append(
                {
                    "Scenario": name,
                    "Customers": len(comparison),
                    "ChangedFromBase": int(
                        (
                            comparison["CommercialSegment"]
                            != comparison["SensitivitySegment"]
                        ).sum()
                    ),
                    "ChangedPct": float(
                        (
                            comparison["CommercialSegment"]
                            != comparison["SensitivitySegment"]
                        ).mean()
                    ),
                    "SegmentCounts": json.dumps(
                        comparison["SensitivitySegment"]
                        .value_counts()
                        .reindex(SEGMENTS, fill_value=0)
                        .to_dict(),
                        sort_keys=True,
                    ),
                }
            )
        sensitivity = pd.DataFrame(sensitivity_rows)

        decline_test_summary = risk_validation.loc[
            (risk_validation["RiskType"] == "Decline")
            & (risk_validation["ValidationSplit"] == "Temporal holdout")
        ].iloc[0].to_dict()
        inactivity_test_summary = risk_validation.loc[
            (risk_validation["RiskType"] == "Inactivity")
            & (risk_validation["ValidationSplit"] == "Temporal holdout")
        ].iloc[0].to_dict()
        inactivity_validation_status = (
            "Not empirically validated: no positive inactivity outcomes in the "
            "development or temporal-holdout periods."
            if int(
                risk_validation.loc[
                    risk_validation["RiskType"] == "Inactivity", "outcomes"
                ].sum()
            )
            == 0
            else "Temporally evaluated."
        )

        segment_config = pd.DataFrame(
            [
                {
                    "ModelVersion": SEGMENT_VERSION,
                    "MinimumHistoryMonths": MIN_HISTORY_MONTHS,
                    "ValueMeaningfulPercentile": 50,
                    "MomentumDeteriorationPercentile": 30,
                    "MomentumImprovingPercentile": 70,
                    "EngagementLowPercentile": 30,
                    "EngagementCrediblePercentile": 50,
                    "RuleOrder": (
                        "Insufficient history; meaningful value plus sustained "
                        "deterioration => Risk; other meaningful value => Core; "
                        "improving momentum plus credible engagement => Potential; "
                        "otherwise Low Priority/Dormant. Risk and Potential "
                        "candidate changes require two consecutive monthly "
                        "classifications before changing the assigned segment."
                    ),
                    "ThresholdBasis": (
                        "Within-AsOfMonth empirical score percentiles; no absolute "
                        "sales/growth cutoff."
                    ),
                    "ConfirmationMonths": 2,
                    "CommercialQualityGatesSegment": False,
                }
            ]
        )
        risk_config = pd.DataFrame(
            [
                {
                    "RiskType": "Decline",
                    "ModelVersion": RISK_VERSION,
                    "HistoryMonths": MIN_HISTORY_MONTHS,
                    "OutcomeHorizonMonths": 3,
                    "LabelDefinition": (
                        "Next-three-month Net Sales / (3 × as-of trailing "
                        "three-month average) is at or below the development "
                        "period's 25th percentile, and at least 2 of 3 future "
                        "monthly sales values are below the as-of trailing "
                        "three-month monthly average."
                    ),
                    "OutcomeTrainingPeriod": (
                        "2025-06 through 2025-09 as-of months; future outcomes "
                        "end by 2025-12."
                    ),
                    "LowScoreCutoff": low_decline_cutoff,
                    "HighScoreCutoff": high_decline_cutoff,
                    "ThresholdMethod": decline_threshold_method,
                    "TrainingYoudenCutoffDiagnostic": youden_cutoff,
                    "TrainingYoudenJDiagnostic": youden,
                    "TrainingDirectionAUCBeforeOrientation": raw_direction_auc,
                    "ScoreDirection": (
                        "Inverted from adverse-trend percentile because the "
                        "development outcomes associated below-baseline decline "
                        "with the opposite score direction."
                        if decline_score_inverted
                        else "Adverse trend percentile."
                    ),
                    "ProbabilityCalibrated": False,
                },
                {
                    "RiskType": "Inactivity",
                    "ModelVersion": RISK_VERSION,
                    "HistoryMonths": MIN_HISTORY_MONTHS,
                    "OutcomeHorizonMonths": 3,
                    "LabelDefinition": (
                        "No transactions in the next 3 complete months AND the "
                        "gap from the last known purchase to the end of that "
                        "future window exceeds the customer's trailing-12-month "
                        "mean purchase interval known as of the cutoff."
                    ),
                    "OutcomeTrainingPeriod": (
                        "2025-06 through 2025-09 as-of months; future outcomes "
                        "end by 2025-12."
                    ),
                    "LowScoreCutoff": low_inactivity_cutoff,
                    "HighScoreCutoff": high_inactivity_cutoff,
                    "ThresholdMethod": inactivity_threshold_method,
                    "YoudenJ": inactivity_youden,
                    "ProbabilityCalibrated": False,
                    "ValidationStatus": inactivity_validation_status,
                },
            ]
        )

        output_columns = [
            "CustomerID",
            "AsOfMonth",
            "CommercialSegment",
            *COMPONENTS,
            "DeclineRiskScore",
            "DeclineRiskLevel",
            "InactivityRiskScore",
            "InactivityRiskLevel",
            "InactivityRiskEligible",
            "PrimaryRiskDriver",
            "PortfolioState",
            "Trailing12MonthSales",
            "Trailing12MonthGrossMargin",
            "NetSales",
            "Trailing3MonthSalesAverage",
            "AsOfDate",
            "ModelOrRuleVersion",
            "RunDate",
        ]
        segment_frame["ModelOrRuleVersion"] = MODEL_VERSION
        segment_frame["RunDate"] = args.run_date
        segment_frame["AsOfMonth"] = segment_frame["AsOfMonth"].dt.date
        segment_frame["AsOfDate"] = segment_frame["AsOfDate"].dt.date
        segment_frame["DeclineRiskLevel"] = segment_frame[
            "DeclineRiskLevel"
        ].astype("string")
        segment_frame["InactivityRiskLevel"] = segment_frame[
            "InactivityRiskLevel"
        ].astype("string")
        main_output = segment_frame[output_columns].copy()

        grain = ["CustomerID", "AsOfMonth", "ModelOrRuleVersion"]
        if main_output[grain].isna().any(axis=None):
            raise ValueError("Final scoring output contains a null grain key.")
        if main_output.duplicated(grain).any():
            raise ValueError("Final scoring output has duplicate versioned grain keys.")
        if main_output["CommercialSegment"].isna().any():
            raise ValueError("Segment assignment is incomplete.")
        score_missing = {
            "decline_eligible_missing": int(
                segment_frame.loc[
                    segment_frame["HistoryMonths"] >= MIN_HISTORY_MONTHS,
                    "DeclineRiskScore",
                ].isna().sum()
            ),
            "inactivity_eligible_missing": int(
                segment_frame.loc[
                    segment_frame["InactivityRiskEligible"],
                    "InactivityRiskScore",
                ].isna().sum()
            ),
        }
        if any(score_missing.values()):
            raise ValueError(f"Risk scores missing for eligible rows: {score_missing}")

        latest_summary = {
            "as_of_date": "2026-09-30",
            "customers": int(latest["CustomerID"].nunique()),
            "segment_counts": segment_counts,
            "high_decline_risk_customers": int(high_decline["CustomerID"].nunique()),
            "high_inactivity_risk_customers": int(
                high_inactivity["CustomerID"].nunique()
            ),
            "both_high_risk_customers": len(overlap_customers),
            "high_decline_trailing_sales": float(
                high_decline["Trailing12MonthSales"].sum()
            ),
            "high_decline_trailing_gross_margin": float(
                high_decline["Trailing12MonthGrossMargin"].sum()
            ),
            "high_inactivity_trailing_sales": float(
                high_inactivity["Trailing12MonthSales"].sum()
            ),
            "high_inactivity_trailing_gross_margin": float(
                high_inactivity["Trailing12MonthGrossMargin"].sum()
            ),
            "segment_and_risk_groups": current_risk_groups.to_dict("records"),
            "primary_risk_drivers": current_primary_drivers.to_dict("records"),
        }
        summary = {
            "model_version": MODEL_VERSION,
            "run_date": args.run_date.isoformat(),
            "as_of_date": "2026-09-30",
            "customer_feature_rows": len(scored),
            "output_rows": len(main_output),
            "history_rule": (
                f"At least {MIN_HISTORY_MONTHS} consecutive observed customer-month "
                "rows since first observed purchase."
            ),
            "score_definitions": {
                "ValueScore": (
                    "Mean within-month percentile rank of trailing-12-month sales, "
                    "trailing-12-month gross margin, and trailing-12-month sales "
                    "per active month."
                ),
                "MomentumScore": (
                    "Mean within-month percentile rank of recent sales trend, "
                    "recent quantity trend, and the difference between active "
                    "months in the latest 3 versus the preceding 3."
                ),
                "EngagementScore": (
                    "Mean within-month percentile rank of purchase frequency, "
                    "active months, consistency, and inverse recency divided by "
                    "historical average purchase interval."
                ),
                "CommercialQualityScore": (
                    "Mean within-month percentile rank of trailing-12-month "
                    "gross margin percentage and inverse discount/return ratios; "
                    "context only and not a segment gate."
                ),
                "DeclineRiskScore": (
                    "Composite of sales/quantity/activity trend ranks. Direction is "
                    "set using development-period outcome association only; see "
                    "the score-direction threshold/configuration record."
                ),
                "InactivityRiskScore": (
                    "Mean percentile rank of elevated recency-to-cadence ratio, "
                    "lower recent purchase frequency, lower purchase consistency, "
                    "and fewer active months."
                ),
            },
            "segment_definitions": {
                "POTENTIAL": (
                    "At least 6 months; momentum at or above that month's 70th "
                    "percentile and engagement at or above that month's median; "
                    "candidate state must persist for 2 consecutive months."
                ),
                "CORE / MAINTAIN": (
                    "At least 6 months; value at or above that month's median, "
                    "without the defined deterioration rule."
                ),
                "RISK / DECLINING": (
                    "At least 6 months; value at or above that month's median and "
                    "momentum at/below its 30th percentile, or low engagement "
                    "(30th percentile or below) together with negative active-month "
                    "trend; candidate state must persist for 2 consecutive months."
                ),
                "LOW PRIORITY / DORMANT": (
                    "At least 6 months and not meeting Potential, Core, or "
                    "Risk/Declining rules; low relative value without qualifying "
                    "growth is not necessarily literal inactivity."
                ),
                "INSUFFICIENT HISTORY": (
                    "Fewer than 6 observed customer-months; no segment or risk score."
                ),
            },
            "current_snapshot": latest_summary,
            "thresholds": {
                "decline_outcome_ratio_training_p25": decline_ratio_threshold,
                "decline_level_low": low_decline_cutoff,
                "decline_level_high": high_decline_cutoff,
                "decline_level_method": decline_threshold_method,
                "decline_training_direction_auc_before_orientation": raw_direction_auc,
                "decline_training_youden_j_diagnostic": youden,
                "inactivity_level_low": low_inactivity_cutoff,
                "inactivity_level_high": high_inactivity_cutoff,
                "inactivity_level_method": inactivity_threshold_method,
                "inactivity_development_positive_outcomes": inactivity_label_events,
            },
            "mature_outcome_windows": {
                "all_months": int(outcomes["AsOfMonth"].nunique()),
                "first_asof_month": outcomes["AsOfMonth"].min().strftime("%Y-%m"),
                "last_asof_month": outcomes["AsOfMonth"].max().strftime("%Y-%m"),
                "development_months": int(
                    outcomes.loc[
                        outcomes["AsOfMonth"] <= DECLINE_TRAIN_END, "AsOfMonth"
                    ].nunique()
                ),
                "holdout_months": int(
                    outcomes.loc[
                        outcomes["AsOfMonth"].between(
                            DECLINE_TEST_START, DECLINE_TEST_END
                        ),
                        "AsOfMonth",
                    ].nunique()
                ),
                "outcome_window_gap_months": ["2025-10", "2025-11", "2025-12"],
            },
            "decline_validation": {
                "outcome_definition": (
                    "Future 3-month sales divided by three times the as-of trailing "
                    "3-month monthly average is at/below the development-period "
                    "25th percentile, with at least 2 of 3 future months below the "
                    "as-of trailing 3-month monthly average."
                ),
                "development_ratio_threshold": decline_ratio_threshold,
                "risk_score_threshold_method": decline_threshold_method,
                "development_youden_j": youden,
                "temporal_holdout": decline_test_summary,
            },
            "inactivity_validation": {
                "outcome_definition": (
                    "Zero transactions in the next 3 complete months and the gap "
                    "from last purchase to future-window end exceeds that customer's "
                    "trailing-12-month average purchase interval as known at cutoff."
                ),
                "status": inactivity_validation_status,
                "temporal_holdout": inactivity_test_summary,
            },
            "segment_validation": {
                "summary": segment_validation.to_dict("records"),
                "transition_observations": transition_count,
                "unchanged_segment_rate": stability,
                "mature_transition_observations": mature_transition_count,
                "mature_unchanged_segment_rate": mature_stability,
                "transition_matrix": transition_matrix.to_dict("records"),
                "sensitivity": sensitivity.to_dict("records"),
            },
            "risk_score_completeness": score_missing,
            "limitations": [
                "Only 21 months of history; supervised outcome windows are available for 13 as-of months.",
                "Customer observations within a three-month horizon overlap; outcomes are correlated across adjacent origins.",
                "Decline labels are relative to a development-period percentile and are not calibrated probabilities.",
                "No positive three-month inactivity outcomes were observed; inactivity score levels are provisional relative tiers and predictive performance is unvalidated.",
                "Cross-sectional percentile scores describe relative position, not absolute commercial thresholds.",
                "Customer dimensions are not historized; historic distributor/rep/customer assignments are unavailable.",
                "Returns, margin and discount are descriptive context and do not cause segment/risk assignment except margin as a component of relative value/quality score.",
            ],
        }

        segment_validation["ModelVersion"] = MODEL_VERSION
        transition_matrix["ModelVersion"] = MODEL_VERSION
        transition_by_month["ModelVersion"] = MODEL_VERSION
        sensitivity["ModelVersion"] = MODEL_VERSION
        risk_validation["ModelVersion"] = MODEL_VERSION
        segment_config["RunDate"] = args.run_date
        risk_config["RunDate"] = args.run_date
        outcomes["ModelVersion"] = MODEL_VERSION
        outcomes["RunDate"] = args.run_date

        exports = {
            "fact_customer_segment_risk": main_output,
            "customer_segment_validation_summary": segment_validation,
            "customer_segment_transition_matrix": transition_matrix.reset_index(drop=True),
            "customer_segment_transition_by_month": transition_by_month,
            "customer_segment_threshold_config": segment_config,
            "customer_risk_validation_results": risk_validation,
            "customer_risk_threshold_config": risk_config,
            "customer_risk_backtest": outcomes[
                [
                    "CustomerID",
                    "AsOfMonth",
                    "HistoryMonths",
                    "Trailing3MonthSalesAverage",
                    "FutureSales3Month",
                    "FutureSalesToBaselineRatio",
                    "FutureMonthsBelowSalesBaseline",
                    "DeclineLabel",
                    "FutureTransactions3Month",
                    "FutureActiveMonths3",
                    "FutureGapDays",
                    "AveragePurchaseIntervalDaysTrailing12",
                    "InactivityLabel",
                    "DeclineRiskScore",
                    "InactivityRiskScore",
                    "ModelVersion",
                    "RunDate",
                ]
            ].copy(),
            "customer_segment_sensitivity": sensitivity,
            "customer_intelligence_validation": pd.DataFrame(
                [
                    {
                        "AsOfDate": "2026-09-30",
                        "OutputRows": len(main_output),
                        "UniqueCustomerMonthVersionKeys": int(
                            main_output[grain].drop_duplicates().shape[0]
                        ),
                        "IncompleteSegments": int(
                            main_output["CommercialSegment"].isna().sum()
                        ),
                        "EligibleDeclineScoresMissing": score_missing[
                            "decline_eligible_missing"
                        ],
                        "EligibleInactivityScoresMissing": score_missing[
                            "inactivity_eligible_missing"
                        ],
                        "ModelVersion": MODEL_VERSION,
                    }
                ]
            ),
        }
        con.execute("BEGIN TRANSACTION")
        for table, data in exports.items():
            registered = f"input_{table}"
            con.register(registered, data)
            con.execute(
                f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM "{registered}"'
            )

        key_result = con.execute(
            """SELECT COUNT(*),
                      COUNT(DISTINCT (CustomerID, AsOfMonth, ModelOrRuleVersion)),
                      COUNT(*) FILTER (WHERE CustomerID IS NULL OR AsOfMonth IS NULL
                                        OR ModelOrRuleVersion IS NULL),
                      COUNT(*) FILTER (WHERE CommercialSegment IS NULL)
               FROM fact_customer_segment_risk"""
        ).fetchone()
        if key_result != (len(main_output), len(main_output), 0, 0):
            raise ValueError(f"Persisted scoring grain validation failed: {key_result}")
        with tempfile.TemporaryDirectory(
            prefix=".customer-intelligence-", dir=OUTPUT_DIR
        ) as stage:
            for table in exports:
                target = Path(stage) / f"{table}.csv"
                target_sql = str(target).replace("'", "''")
                con.execute(
                    f'COPY "{table}" TO \'{target_sql}\' '
                    "(HEADER, DELIMITER ',', FORMAT CSV)"
                )
            report_path = Path(stage) / "customer_intelligence_validation.json"
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
                Path(OUTPUT_DIR / f"{table}.csv").parent.mkdir(
                    parents=True, exist_ok=True
                )
                (Path(stage) / f"{table}.csv").replace(
                    OUTPUT_DIR / f"{table}.csv"
                )
            report_path.replace(
                OUTPUT_DIR / "customer_intelligence_validation.json"
            )

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
    parser.add_argument("--output-db", type=Path, default=OUTPUT_DB)
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=date(2026, 9, 30))
    parser.add_argument("--run-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
