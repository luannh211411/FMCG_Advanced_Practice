"""Backtest simple sales forecasts and persist forecast-vs-target outputs."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FEATURE_DB = ROOT / "database" / "fmcg_predictive_features.duckdb"
SOURCE_DB = ROOT / "database" / "fmcg_analytics_main.duckdb"
OUTPUT_DB = ROOT / "database" / "fmcg_predictive_outputs.duckdb"
OUTPUT_DIR = ROOT / "processed" / "predictive"
MODEL_VERSION = "fmcg-sales-forecast-v1.0.0"
AS_OF_DATE = date(2026, 9, 30)
HORIZON = 3
MIN_HISTORY_MONTHS = 18
MIN_NONZERO_MONTHS = 18
INITIAL_BACKTEST_HISTORY = 12
ETS_ALPHA = 0.30
ETS_BETA = 0.10
ETS_DAMPING = 0.90
ETS_MIN_GAIN = 0.05
ETS_MAX_ABS_BIAS_DEGRADATION = 0.02
SERIES_KEYS = ("Region", "Channel", "Category")
FORECAST_KEYS = ("ForecastMonth", "Region", "Channel", "Category")
METHOD_ORDER = {
    "last_observed": 0,
    "moving_average_3": 1,
    "linear_trend_6": 2,
    "seasonal_naive_12": 3,
    "holt_damped": 4,
}
METHOD_LABELS = {
    "last_observed": "Last observed month",
    "moving_average_3": "Trailing 3-month average",
    "linear_trend_6": "Linear trend (last 6 months)",
    "seasonal_naive_12": "Seasonal naive (12 months)",
    "holt_damped": "Damped Holt exponential smoothing",
}


def month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def month_end(value: date) -> date:
    return add_months(month_start(value), 1) - timedelta(days=1)


def damped_holt(values: np.ndarray, horizon: int) -> list[float]:
    if len(values) < 2:
        raise ValueError("Damped Holt requires at least two observations.")
    level = float(values[0])
    trend = float(values[1] - values[0])
    for observation in values[1:]:
        previous_level = level
        level = ETS_ALPHA * float(observation) + (1 - ETS_ALPHA) * (
            previous_level + ETS_DAMPING * trend
        )
        trend = ETS_BETA * (level - previous_level) + (
            1 - ETS_BETA
        ) * ETS_DAMPING * trend
    output = []
    for step in range(1, horizon + 1):
        damped_multiplier = sum(ETS_DAMPING**power for power in range(1, step + 1))
        output.append(level + damped_multiplier * trend)
    return output


def project_raw(method: str, values: np.ndarray, horizon: int) -> list[float]:
    if not len(values):
        raise ValueError("Cannot forecast an empty series.")
    if method == "last_observed":
        raw = [float(values[-1])] * horizon
    elif method == "moving_average_3":
        if len(values) < 3:
            raise ValueError("Moving average requires three observations.")
        raw = [float(np.mean(values[-3:]))] * horizon
    elif method == "linear_trend_6":
        window = values[-min(6, len(values)) :]
        x = np.arange(len(values) - len(window), len(values), dtype=float)
        slope, intercept = np.polyfit(x, window, 1)
        raw = [
            float(intercept + slope * (len(values) - 1 + step))
            for step in range(1, horizon + 1)
        ]
    elif method == "seasonal_naive_12":
        raw = []
        for step in range(1, horizon + 1):
            source_index = len(values) + step - 1 - 12
            if source_index < 0:
                raise ValueError("Seasonal naive requires 12 prior monthly values.")
            raw.append(float(values[source_index]))
    elif method == "holt_damped":
        raw = damped_holt(values, horizon)
    else:
        raise ValueError(f"Unknown forecast method: {method}")
    return raw


def project(method: str, values: np.ndarray, horizon: int) -> list[float]:
    return [max(0.0, value) for value in project_raw(method, values, horizon)]


def metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "evaluated_forecasts": 0,
            "evaluated_series": 0,
            "actual_total": 0.0,
            "forecast_total": 0.0,
            "wape": None,
            "bias": None,
            "mae": None,
        }
    actual = np.asarray([record["ActualSales"] for record in records], dtype=float)
    forecast = np.asarray([record["ForecastSales"] for record in records], dtype=float)
    errors = forecast - actual
    actual_total = float(actual.sum())
    return {
        "evaluated_forecasts": len(records),
        "evaluated_series": len(
            {
                (record["Region"], record["Channel"], record["Category"])
                for record in records
            }
        ),
        "actual_total": actual_total,
        "forecast_total": float(forecast.sum()),
        "wape": (
            float(np.abs(errors).sum() / abs(actual_total))
            if actual_total != 0
            else None
        ),
        "bias": float(errors.sum() / actual_total) if actual_total != 0 else None,
        "mae": float(np.abs(errors).mean()),
    }


def get_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature-db", type=Path, default=FEATURE_DB)
    parser.add_argument("--source-db", type=Path, default=SOURCE_DB)
    parser.add_argument("--output-db", type=Path, default=OUTPUT_DB)
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=AS_OF_DATE)
    parser.add_argument("--run-date", type=date.fromisoformat, default=date.today())
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict[str, Any]:
    for source in (args.feature_db, args.source_db):
        if not source.is_file():
            raise FileNotFoundError(f"Required input database is missing: {source}")
    if args.output_db.resolve() in {
        args.feature_db.resolve(),
        args.source_db.resolve(),
    }:
        raise ValueError("Output database must be separate from both source databases.")
    if args.as_of_date != AS_OF_DATE:
        raise ValueError(
            f"Build 2 is scoped to the approved sales cutoff {AS_OF_DATE}; "
            "future actuals are not permitted."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.output_db))
    try:
        feature_path = str(args.feature_db.resolve()).replace("'", "''")
        source_path = str(args.source_db.resolve()).replace("'", "''")
        con.execute(f"ATTACH '{feature_path}' AS features (READ_ONLY)")
        con.execute(f"ATTACH '{source_path}' AS analytical (READ_ONLY)")

        feature_bounds = con.execute(
            """SELECT MIN(MonthStart), MAX(MonthStart), COUNT(DISTINCT MonthStart)
               FROM features.main.feature_sales_monthly"""
        ).fetchone()
        if feature_bounds != (date(2025, 1, 1), date(2026, 9, 1), 21):
            raise ValueError(
                "Unexpected Build 1 history. Required Jan-2025 through Sep-2026 "
                f"(21 months), received {feature_bounds}."
            )
        feature_key_check = con.execute(
            """SELECT COUNT(*) AS rows,
                      COUNT(DISTINCT (
                          MonthStart, Region, Channel, Category
                      )) AS distinct_keys,
                      COUNT(*) FILTER (
                          WHERE MonthStart IS NULL OR Region IS NULL
                             OR Channel IS NULL OR Category IS NULL
                      ) AS null_keys
               FROM features.main.feature_sales_monthly"""
        ).fetchone()
        if (
            feature_key_check[0] != feature_key_check[1]
            or feature_key_check[2] != 0
        ):
            raise ValueError(
                f"Build 1 feature grain is not unique and complete: {feature_key_check}"
            )

        feature_df = con.execute(
            """SELECT MonthStart, Region, Channel, Category, NetSales
               FROM features.main.feature_sales_monthly
               ORDER BY Region, Channel, Category, MonthStart"""
        ).fetchdf()
        keys = list(SERIES_KEYS)
        full_months = [add_months(date(2025, 1, 1), i) for i in range(21)]
        series_data: dict[tuple[str, str, str], np.ndarray] = {}
        series_coverage: list[dict[str, Any]] = []
        for key, group in feature_df.groupby(keys, sort=True, dropna=False):
            values_by_month = dict(zip(group["MonthStart"].dt.date, group["NetSales"]))
            values = np.asarray(
                [float(values_by_month.get(month, np.nan)) for month in full_months],
                dtype=float,
            )
            if any(not np.isfinite(value) for value in values):
                raise ValueError(f"Incomplete or null feature history for series {key}.")
            nonzero_months = int(np.count_nonzero(values))
            latest_three_nonzero = int(np.count_nonzero(values[-3:]))
            eligible = (
                len(values) >= MIN_HISTORY_MONTHS
                and nonzero_months >= MIN_NONZERO_MONTHS
                and latest_three_nonzero > 0
            )
            series_data[key] = values
            series_coverage.append(
                {
                    "Region": key[0],
                    "Channel": key[1],
                    "Category": key[2],
                    "HistoryMonths": len(values),
                    "NonzeroMonths": nonzero_months,
                    "Latest3NonzeroMonths": latest_three_nonzero,
                    "Eligible": eligible,
                    "Reason": (
                        "Eligible"
                        if eligible
                        else "Insufficient history, nonzero coverage, or recent activity"
                    ),
                }
            )
        eligible_keys = {
            (row["Region"], row["Channel"], row["Category"])
            for row in series_coverage
            if row["Eligible"]
        }
        if not eligible_keys:
            raise ValueError("No series meets the forecast eligibility criteria.")

        methods = (
            "last_observed",
            "moving_average_3",
            "linear_trend_6",
            "seasonal_naive_12",
            "holt_damped",
        )
        cutoffs = [
            add_months(date(2025, 1, 1), i)
            for i in range(INITIAL_BACKTEST_HISTORY - 1, 18)
        ]
        if len(cutoffs) != 7:
            raise ValueError(f"Expected seven rolling cutoffs, got {len(cutoffs)}.")

        backtest_predictions: list[dict[str, Any]] = []
        backtest_coverage: list[dict[str, Any]] = []
        for cutoff in cutoffs:
            train_count = full_months.index(cutoff) + 1
            train_end_date = month_end(cutoff)
            cutoff_keys = []
            minimum_nonzero = int(np.ceil(train_count * 0.80))
            for series_key, complete_values in series_data.items():
                values = complete_values[:train_count]
                if (
                    train_count >= INITIAL_BACKTEST_HISTORY
                    and np.count_nonzero(values) >= minimum_nonzero
                    and np.count_nonzero(values[-min(3, train_count) :]) > 0
                ):
                    cutoff_keys.append(series_key)
            backtest_coverage.append(
                {
                    "BacktestCutoff": train_end_date,
                    "TrainingMonths": train_count,
                    "EligibleSeries": len(cutoff_keys),
                    "TotalSeries": len(series_data),
                    "CoveragePct": len(cutoff_keys) / len(series_data),
                }
            )
            for series_key in sorted(cutoff_keys):
                values = series_data[series_key][:train_count]
                for method in methods:
                    for horizon in range(1, HORIZON + 1):
                        target_month = add_months(cutoff, horizon)
                        actual_index = full_months.index(target_month)
                        raw_forecast = project_raw(method, values, horizon)[horizon - 1]
                        forecast_value = max(0.0, raw_forecast)
                        actual_value = float(series_data[series_key][actual_index])
                        backtest_predictions.append(
                            {
                                "BacktestCutoff": train_end_date,
                                "ForecastMonth": target_month,
                                "Region": series_key[0],
                                "Channel": series_key[1],
                                "Category": series_key[2],
                                "ForecastHorizon": horizon,
                                "ForecastMethod": method,
                                "MethodLabel": METHOD_LABELS[method],
                                "TrainingMonths": train_count,
                                "RawForecastSales": raw_forecast,
                                "ForecastSales": forecast_value,
                                "NegativeForecastClipped": raw_forecast < 0,
                                "ActualSales": actual_value,
                                "ForecastError": forecast_value - actual_value,
                                "AbsoluteError": abs(forecast_value - actual_value),
                            }
                        )

        comparisons = []
        for method in methods:
            method_records = [
                row for row in backtest_predictions
                if row["ForecastMethod"] == method
            ]
            for horizon in range(1, HORIZON + 1):
                horizon_records = [
                    row for row in method_records
                    if row["ForecastHorizon"] == horizon
                ]
                measure = metrics(horizon_records)
                comparisons.append(
                    {
                        "ForecastMethod": method,
                        "MethodLabel": METHOD_LABELS[method],
                        "ForecastHorizon": horizon,
                        "BacktestCutoffs": len(cutoffs),
                        **measure,
                        "EligibleSeries": measure["evaluated_series"],
                        "SeriesCoveragePct": measure["evaluated_series"]
                        / len(series_data),
                        "SelectionStatus": (
                            "Exploratory only: one annual cycle; not eligible for promotion"
                            if method == "seasonal_naive_12"
                            else "Candidate"
                        ),
                    }
                )
            measure = metrics(method_records)
            comparisons.append(
                {
                    "ForecastMethod": method,
                    "MethodLabel": METHOD_LABELS[method],
                    "ForecastHorizon": 0,
                    "BacktestCutoffs": len(cutoffs),
                    **measure,
                    "EligibleSeries": measure["evaluated_series"],
                    "SeriesCoveragePct": measure["evaluated_series"]
                    / len(series_data),
                    "SelectionStatus": (
                        "Exploratory only: one annual cycle; not eligible for promotion"
                        if method == "seasonal_naive_12"
                        else "Candidate"
                    ),
                }
            )

        aggregate_by_method = {
            row["ForecastMethod"]: row
            for row in comparisons
            if row["ForecastHorizon"] == 0
        }
        selectable_baselines = [
            "last_observed",
            "moving_average_3",
            "linear_trend_6",
        ]
        best_baseline = min(
            selectable_baselines,
            key=lambda method: (
                aggregate_by_method[method]["wape"]
                if aggregate_by_method[method]["wape"] is not None
                else float("inf"),
                abs(aggregate_by_method[method]["bias"])
                if aggregate_by_method[method]["bias"] is not None
                else float("inf"),
                METHOD_ORDER[method],
            ),
        )
        selected_method = best_baseline
        candidate = aggregate_by_method["holt_damped"]
        baseline = aggregate_by_method[best_baseline]
        ets_improvement = (
            (baseline["wape"] - candidate["wape"]) / baseline["wape"]
            if baseline["wape"] not in (None, 0) and candidate["wape"] is not None
            else 0.0
        )
        ets_bias_degradation = (
            abs(candidate["bias"]) - abs(baseline["bias"])
            if candidate["bias"] is not None and baseline["bias"] is not None
            else float("inf")
        )
        if (
            ets_improvement >= ETS_MIN_GAIN
            and ets_bias_degradation <= ETS_MAX_ABS_BIAS_DEGRADATION
        ):
            selected_method = "holt_damped"

        final_predictions: list[dict[str, Any]] = []
        for series_key in sorted(eligible_keys):
            values = series_data[series_key]
            raw_values = project_raw(selected_method, values, HORIZON)
            for horizon, raw_forecast in enumerate(raw_values, start=1):
                forecast_value = round(max(0.0, raw_forecast), 2)
                final_predictions.append(
                    {
                        "ForecastMonth": add_months(AS_OF_DATE.replace(day=1), horizon),
                        "Region": series_key[0],
                        "Channel": series_key[1],
                        "Category": series_key[2],
                        "ForecastSales": forecast_value,
                        "NegativeForecastClipped": raw_forecast < 0,
                        "ForecastHorizon": horizon,
                        "ForecastMethod": selected_method,
                        "AsOfDate": AS_OF_DATE,
                        "RunDate": args.run_date,
                        "ModelVersion": MODEL_VERSION,
                    }
                )

        con.register("series_coverage_input", pd.DataFrame(series_coverage))
        con.register("backtest_predictions_input", pd.DataFrame(backtest_predictions))
        con.register("model_comparison_input", pd.DataFrame(comparisons))
        con.register("forecast_input", pd.DataFrame(final_predictions))
        con.execute(
            """CREATE OR REPLACE TEMP TABLE future_targets AS
               SELECT Month AS ForecastMonth, Region, Channel, Category,
                      SalesTarget
               FROM analytical.main.fact_target
               WHERE Month BETWEEN DATE '2026-10-01' AND DATE '2026-12-01'"""
        )
        con.execute(
            """CREATE OR REPLACE TEMP TABLE forecast_gap_input AS
               SELECT
                   f.ForecastMonth,
                   f.Region,
                   f.Channel,
                   f.Category,
                   f.ForecastSales,
                   t.SalesTarget,
                   f.ForecastSales - t.SalesTarget AS ForecastTargetGap,
                   (f.ForecastSales - t.SalesTarget)
                       / NULLIF(t.SalesTarget, 0) AS ForecastTargetGapPct,
                   f.ForecastSales / NULLIF(t.SalesTarget, 0)
                       AS ProjectedTargetAchievementPct,
                   f.ForecastHorizon,
                   f.ForecastMethod,
                   f.AsOfDate,
                   f.RunDate,
                   f.ModelVersion
               FROM forecast_input f
               LEFT JOIN future_targets t USING (
                   ForecastMonth, Region, Channel, Category
               )"""
        )

        key_validation = con.execute(
            """SELECT
                   COUNT(*) AS forecast_rows,
                   COUNT(DISTINCT (ForecastMonth, Region, Channel, Category)) AS unique_keys,
                   COUNT(*) FILTER (
                       WHERE ForecastMonth NOT IN (
                           DATE '2026-10-01', DATE '2026-11-01', DATE '2026-12-01'
                       )
                   ) AS invalid_month_rows,
                   COUNT(*) FILTER (WHERE ForecastSales < 0) AS negative_forecasts
               FROM forecast_input"""
        ).fetchone()
        if key_validation != (len(eligible_keys) * HORIZON, len(eligible_keys) * HORIZON, 0, 0):
            raise ValueError(f"Forecast key/value validation failed: {key_validation}")

        target_validation = con.execute(
            """SELECT
                   COUNT(*) AS output_rows,
                   COUNT(SalesTarget) AS matched_targets,
                   COUNT(*) FILTER (WHERE SalesTarget IS NULL) AS missing_targets,
                   COUNT(*) FILTER (WHERE SalesTarget = 0) AS zero_targets,
                   COUNT(*) FILTER (
                       WHERE SalesTarget = 0 AND (
                           ForecastTargetGapPct IS NOT NULL
                           OR ProjectedTargetAchievementPct IS NOT NULL
                       )
                   ) AS unsafe_zero_target_ratios,
                   COUNT(*) FILTER (
                       WHERE ForecastTargetGap IS DISTINCT FROM
                             ForecastSales - SalesTarget
                   ) AS gap_formula_mismatches
               FROM forecast_gap_input"""
        ).fetchone()
        if (
            target_validation[0] != len(final_predictions)
            or target_validation[1] != len(final_predictions)
            or target_validation[2] != 0
            or target_validation[4] != 0
            or target_validation[5] != 0
        ):
            raise ValueError(f"Target grain/join validation failed: {target_validation}")

        aggregate_forecast = con.execute(
            """SELECT ForecastMonth, SUM(ForecastSales), SUM(SalesTarget),
                      SUM(ForecastTargetGap)
               FROM forecast_gap_input
               GROUP BY ForecastMonth ORDER BY ForecastMonth"""
        ).fetchall()
        if any(abs((row[1] - row[2]) - row[3]) > 0.01 for row in aggregate_forecast):
            raise ValueError("Aggregated forecast gap does not reconcile to forecast less target.")

        coverage_counts = {
            "total_series": len(series_data),
            "eligible_series": len(eligible_keys),
            "insufficient_history_series": len(series_data) - len(eligible_keys),
            "series_coverage_pct": len(eligible_keys) / len(series_data),
        }
        selected_metrics = aggregate_by_method[selected_method]
        result = {
            "model_version": MODEL_VERSION,
            "run_date": args.run_date.isoformat(),
            "as_of_date": AS_OF_DATE.isoformat(),
            "history_months": 21,
            "input_feature_key_validation": {
                "rows": feature_key_check[0],
                "distinct_keys": feature_key_check[1],
                "null_key_rows": feature_key_check[2],
            },
            "forecast_horizon_months": HORIZON,
            "eligibility": {
                "criteria": (
                    f"At least {MIN_HISTORY_MONTHS} complete monthly observations, "
                    f"at least {MIN_NONZERO_MONTHS} nonzero months, and a nonzero "
                    "observation in the latest three months."
                ),
                **coverage_counts,
                "coverage_by_series": series_coverage,
            },
            "backtest": {
                "design": (
                    "Seven rolling origins: 2025-12 through 2026-06. At each origin "
                    "only history through that month is used; forecast horizons 1-3 "
                    "are tested against the next three observed months."
                ),
                "origin_count": len(cutoffs),
                "cutoffs": [month_end(cutoff).isoformat() for cutoff in cutoffs],
                "evaluated_months_per_horizon": len(cutoffs),
                "predictions_per_method_per_horizon": sum(
                    row["EligibleSeries"] for row in backtest_coverage
                ),
                "predictions_per_method_all_horizons": len(backtest_predictions)
                // len(methods),
                "eligibility_by_cutoff": backtest_coverage,
            },
            "methods": comparisons,
            "selected_method": selected_method,
            "selection_rule": (
                "Choose the lowest aggregate WAPE among naive, trailing-3-month "
                "average, and linear-trend baselines; ties favor lower absolute bias "
                "then the simpler method. Promote damped Holt only if WAPE improves "
                f"by at least {ETS_MIN_GAIN:.0%} over the best baseline and absolute "
                f"bias degrades by no more than "
                f"{ETS_MAX_ABS_BIAS_DEGRADATION:.0%}. Seasonal naive is reported "
                "for comparison but excluded from promotion because only one annual "
                "cycle is available."
            ),
            "selected_metrics": selected_metrics,
            "forecast_rows": len(final_predictions),
            "target_join": {
                "rows": target_validation[0],
                "matched_targets": target_validation[1],
                "missing_targets": target_validation[2],
                "zero_targets": target_validation[3],
                "unsafe_zero_target_ratios": target_validation[4],
                "gap_formula_mismatches": target_validation[5],
                "monthly_aggregates": [
                    {
                        "forecast_month": row[0].isoformat(),
                        "forecast_sales": row[1],
                        "sales_target": row[2],
                        "forecast_target_gap": row[3],
                    }
                    for row in aggregate_forecast
                ],
            },
            "negative_forecast_treatment": (
                "Forecasts below zero are floored at zero because net sales cannot "
                "be negative in the modeled business target. The count of clipped "
                "backtest forecasts is retained in the detailed backtest table."
            ),
            "prediction_intervals": "Not produced; 21 months do not justify validated bounds.",
        }

        con.execute("BEGIN TRANSACTION")
        con.execute(
            """CREATE OR REPLACE TABLE forecast_series_coverage AS
               SELECT * FROM series_coverage_input"""
        )
        con.execute(
            """CREATE OR REPLACE TABLE fact_forecast_backtest AS
               SELECT * FROM backtest_predictions_input"""
        )
        con.execute(
            """CREATE OR REPLACE TABLE forecast_model_comparison AS
               SELECT * FROM model_comparison_input"""
        )
        con.execute(
            """CREATE OR REPLACE TABLE fact_sales_forecast AS
               SELECT * FROM forecast_input"""
        )
        con.execute(
            """CREATE OR REPLACE TABLE fact_forecast_target_gap AS
               SELECT * FROM forecast_gap_input"""
        )

        with tempfile.TemporaryDirectory(prefix=".forecast-build-", dir=OUTPUT_DIR) as stage:
            for table in (
                "fact_sales_forecast",
                "fact_forecast_target_gap",
                "fact_forecast_backtest",
                "forecast_model_comparison",
                "forecast_series_coverage",
            ):
                target = Path(stage) / f"{table}.csv"
                target_sql = str(target).replace("'", "''")
                con.execute(
                    f"COPY {table} TO '{target_sql}' "
                    "(HEADER, DELIMITER ',', FORMAT CSV)"
                )
            summary_path = Path(stage) / "forecast_validation.json"
            summary_path.write_text(
                json.dumps(result, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            con.execute("COMMIT")
            for table in (
                "fact_sales_forecast",
                "fact_forecast_target_gap",
                "fact_forecast_backtest",
                "forecast_model_comparison",
                "forecast_series_coverage",
            ):
                os.replace(Path(stage) / f"{table}.csv", OUTPUT_DIR / f"{table}.csv")
            os.replace(summary_path, OUTPUT_DIR / "forecast_validation.json")

        return result
    except Exception:
        try:
            con.execute("ROLLBACK")
        except duckdb.Error:
            pass
        raise
    finally:
        con.close()


def main() -> None:
    args = get_cli_args()
    result = run(args)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
