"""Build the V1 predictive feature tables from the validated DuckDB model."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "database" / "fmcg_analytics_main.duckdb"
FEATURE_DB = ROOT / "database" / "fmcg_predictive_features.duckdb"
SQL_FILE = ROOT / "src" / "sql" / "predictive_features.sql"
OUTPUT_DIR = ROOT / "processed" / "features"

FEATURE_TABLES = (
    "feature_sales_monthly",
    "feature_customer_monthly",
    "feature_inventory_risk",
)
SOURCE_TABLES = (
    "fact_sales",
    "fact_returns",
    "fact_inventory",
    "dim_customer",
    "dim_product",
    "dim_date",
)
KEYS = {
    "feature_sales_monthly": ("MonthStart", "Region", "Channel", "Category"),
    "feature_customer_monthly": ("CustomerID", "AsOfMonth"),
    "feature_inventory_risk": ("SnapshotDate", "DistributorID", "ProductID"),
}
TOLERANCE = 0.01


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Date must use YYYY-MM-DD format.") from exc


def scalar(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    parameters: list[Any] | None = None,
) -> Any:
    return con.execute(sql, parameters or []).fetchone()[0]


def table_profile(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, Any]:
    columns = [row[0] for row in con.execute(f"DESCRIBE {table}").fetchall()]
    expressions = [
        f'COUNT(*) FILTER (WHERE "{column.replace(chr(34), chr(34) * 2)}" IS NULL)'
        for column in columns
    ]
    values = con.execute(
        f"SELECT COUNT(*), {', '.join(expressions)} FROM {table}"
    ).fetchone()
    total = values[0]
    nulls = {
        column: {"count": count, "percent": count / total}
        for column, count in zip(columns, values[1:])
        if count
    }
    return {"rows": total, "columns": columns, "nulls": nulls}


def validate_unique_keys(
    con: duckdb.DuckDBPyConnection,
    table: str,
    keys: tuple[str, ...],
) -> dict[str, int]:
    key_sql = ", ".join(f'"{key}"' for key in keys)
    null_predicate = " OR ".join(f'"{key}" IS NULL' for key in keys)
    null_keys = scalar(
        con, f"SELECT COUNT(*) FROM {table} WHERE {null_predicate}"
    )
    duplicates = scalar(
        con,
        f"""SELECT COUNT(*) FROM (
            SELECT {key_sql} FROM {table}
            GROUP BY {key_sql} HAVING COUNT(*) > 1
        )""",
    )
    return {"null_key_rows": null_keys, "duplicate_key_groups": duplicates}


def validate_window_features(
    con: duckdb.DuckDBPyConnection,
    table: str,
    partition: tuple[str, ...],
    order: str,
    checks: dict[str, str],
) -> dict[str, int]:
    partition_sql = ", ".join(f'"{column}"' for column in partition)
    mismatches: dict[str, int] = {}
    for feature, expected in checks.items():
        mismatches[feature] = scalar(
            con,
            f"""SELECT COUNT(*) FROM (
                SELECT
                    "{feature}",
                    {expected} OVER (
                        PARTITION BY {partition_sql}
                        ORDER BY "{order}"
                    ) AS expected_value
                FROM {table}
            ) q
            WHERE "{feature}" IS DISTINCT FROM expected_value""",
        )
    return mismatches


def run_build(source_db: Path, feature_db: Path, as_of_date: date) -> dict[str, Any]:
    if not source_db.is_file():
        raise FileNotFoundError(f"Validated analytical database not found: {source_db}")
    if not SQL_FILE.is_file():
        raise FileNotFoundError(f"Feature SQL not found: {SQL_FILE}")
    if source_db.resolve() == feature_db.resolve():
        raise ValueError("Feature tables must not overwrite the validated source database.")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(feature_db))
    try:
        source_literal = str(source_db.resolve()).replace("'", "''")
        con.execute(f"ATTACH '{source_literal}' AS source_model (READ_ONLY)")
        for table in SOURCE_TABLES:
            con.execute(
                f"CREATE OR REPLACE TEMP VIEW {table} AS "
                f"SELECT * FROM source_model.main.{table}"
            )

        latest_snapshot = scalar(
            con, "SELECT MAX(SnapshotDate) FROM fact_inventory"
        )
        if latest_snapshot is None:
            raise ValueError("Inventory source has no snapshots.")
        if as_of_date < latest_snapshot:
            raise ValueError(
                f"As-of date {as_of_date} precedes latest inventory snapshot "
                f"{latest_snapshot}."
            )
        con.execute(f"SET VARIABLE feature_as_of_date = DATE '{as_of_date.isoformat()}'")

        sql_text = SQL_FILE.read_text(encoding="utf-8")
        if "fact_target" in sql_text.casefold():
            raise ValueError("Target data must not be used in predictor feature SQL.")
        con.execute("BEGIN TRANSACTION")
        con.execute(sql_text)

        source_bounds = con.execute(
            """SELECT MIN("Date"), MAX("Date"),
                      date_trunc('month', MIN("Date"))::DATE,
                      date_trunc('month', MAX("Date"))::DATE
               FROM fact_sales"""
        ).fetchone()
        first_sales_date, latest_sales_date, first_sales_month, latest_sales_month = source_bounds
        sales_months = con.execute(
            """SELECT date_trunc('month', "Date")::DATE AS month_start,
                      COUNT(*) AS transaction_count,
                      COUNT(DISTINCT SourceFile) AS source_file_count,
                      MIN("Date") AS first_fact_date,
                      MAX("Date") AS last_fact_date,
                      SUM(NetSales) AS net_sales,
                      SUM(Qty) AS quantity
               FROM fact_sales
               GROUP BY 1 ORDER BY 1"""
        ).fetchall()
        expected_months = (
            con.execute(
                """SELECT COUNT(*) FROM (
                       SELECT DISTINCT MonthStart FROM dim_date
                       WHERE MonthStart BETWEEN ? AND ?
                   )""",
                [first_sales_month, latest_sales_month],
            ).fetchone()[0]
        )
        # The source is delivered as one monthly extract per month; boundary dates
        # and one source file per month are the available completeness evidence.
        is_calendar_complete = (
            first_sales_date.day == 1
            and latest_sales_date == con.execute(
                "SELECT last_day(?)", [latest_sales_date]
            ).fetchone()[0]
            and len(sales_months) == expected_months
            and all(
                row[3].day == 1
                and row[4] == con.execute(
                    "SELECT last_day(?)", [row[0]]
                ).fetchone()[0]
                and row[2] == 1
                for row in sales_months
            )
        )
        if not is_calendar_complete:
            raise ValueError(
                "Sales history is not a continuous sequence of boundary-complete "
                "months with one source file per month; feature calendar scaffold "
                "requires complete month coverage."
            )

        sales_rows = scalar(con, "SELECT COUNT(*) FROM fact_sales")
        source_sales_customers = scalar(
            con, "SELECT COUNT(DISTINCT CustomerID) FROM fact_sales"
        )
        dimension_customers = scalar(con, "SELECT COUNT(*) FROM dim_customer")
        customers_without_sales = scalar(
            con,
            """SELECT COUNT(*) FROM dim_customer c
               WHERE NOT EXISTS (
                   SELECT 1 FROM fact_sales s WHERE s.CustomerID = c.CustomerID
               )""",
        )
        sales_before_join_date = con.execute(
            """SELECT COUNT(*), COUNT(DISTINCT s.CustomerID)
               FROM fact_sales s JOIN dim_customer c USING (CustomerID)
               WHERE s."Date" < c.JoinDate"""
        ).fetchone()

        profiles = {table: table_profile(con, table) for table in FEATURE_TABLES}
        key_checks = {
            table: validate_unique_keys(con, table, KEYS[table])
            for table in FEATURE_TABLES
        }
        for table, result in key_checks.items():
            if result["null_key_rows"] or result["duplicate_key_groups"]:
                raise ValueError(f"Key validation failed for {table}: {result}")

        max_month_end = con.execute(
            "SELECT last_day(?)", [latest_sales_month]
        ).fetchone()[0]
        customer_range = con.execute(
            """SELECT MIN(AsOfMonth), MAX(AsOfMonth), COUNT(DISTINCT CustomerID),
                      COUNT(*) FILTER (WHERE AsOfDate > ?)
               FROM feature_customer_monthly""",
            [max_month_end],
        ).fetchone()
        if customer_range[1] != latest_sales_month or customer_range[3] != 0:
            raise ValueError("Customer as-of features extend beyond the sales cutoff.")

        invalid_values = {
            "sales_negative_quantity": scalar(
                con, "SELECT COUNT(*) FROM feature_sales_monthly WHERE Quantity < 0"
            ),
            "sales_negative_transaction_count": scalar(
                con,
                "SELECT COUNT(*) FROM feature_sales_monthly WHERE TransactionCount < 0",
            ),
            "customer_negative_quantity": scalar(
                con, "SELECT COUNT(*) FROM feature_customer_monthly WHERE Quantity < 0"
            ),
            "customer_negative_days_since_purchase": scalar(
                con,
                """SELECT COUNT(*) FROM feature_customer_monthly
                   WHERE DaysSinceLastPurchase < 0""",
            ),
            "customer_invalid_active_month": scalar(
                con,
                """SELECT COUNT(*) FROM feature_customer_monthly
                   WHERE ActiveMonth NOT IN (0, 1)""",
            ),
            "inventory_negative_quantities_or_points": scalar(
                con,
                """SELECT COUNT(*) FROM feature_inventory_risk
                   WHERE OnHandQuantity < 0 OR InTransitQuantity < 0
                      OR ReorderPoint < 0 OR ExpiredQuantity < 0
                      OR Trailing3CompleteMonthsSalesQuantity < 0
                      OR Prior3CompleteMonthsSalesQuantity < 0""",
            ),
            "inventory_negative_freshness": scalar(
                con,
                """SELECT COUNT(*) FROM feature_inventory_risk
                   WHERE SnapshotFreshnessDays < 0""",
            ),
            "inventory_invalid_exception_flag": scalar(
                con,
                """SELECT COUNT(*) FROM feature_inventory_risk
                   WHERE CurrentReorderException NOT IN (0, 1)""",
            ),
        }
        if any(invalid_values.values()):
            raise ValueError(f"Impossible-value validation failed: {invalid_values}")

        sales_lag_checks = validate_window_features(
            con,
            "feature_sales_monthly",
            ("Region", "Channel", "Category"),
            "MonthStart",
            {
                "SalesLag1Month": 'LAG("NetSales", 1)',
                "SalesLag3Months": 'LAG("NetSales", 3)',
                "SalesLag12Months": 'LAG("NetSales", 12)',
                "QuantityLag1Month": 'LAG("Quantity", 1)',
                "QuantityLag3Months": 'LAG("Quantity", 3)',
            },
        )
        sales_window_mismatches = scalar(
            con,
            """SELECT COUNT(*) FROM (
                SELECT Trailing3MonthSalesAverage,
                       Trailing3MonthQuantityAverage,
                       AVG(NetSales) OVER (
                           PARTITION BY Region, Channel, Category
                           ORDER BY MonthStart ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                       ) AS expected_sales,
                       AVG(Quantity) OVER (
                           PARTITION BY Region, Channel, Category
                           ORDER BY MonthStart ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                       ) AS expected_quantity
                FROM feature_sales_monthly
            ) q
            WHERE Trailing3MonthSalesAverage IS DISTINCT FROM expected_sales
               OR Trailing3MonthQuantityAverage IS DISTINCT FROM expected_quantity""",
        )
        customer_window_mismatches = scalar(
            con,
            """SELECT COUNT(*) FROM (
                SELECT CustomerID, AsOfMonth,
                       SalesLag1Month,
                       LAG(NetSales, 1) OVER (
                           PARTITION BY CustomerID ORDER BY AsOfMonth
                       ) AS expected_lag,
                       SalesLag3Months,
                       LAG(NetSales, 3) OVER (
                           PARTITION BY CustomerID ORDER BY AsOfMonth
                       ) AS expected_lag_3,
                       QuantityLag1Month,
                       LAG(Quantity, 1) OVER (
                           PARTITION BY CustomerID ORDER BY AsOfMonth
                       ) AS expected_quantity_lag,
                       QuantityLag3Months,
                       LAG(Quantity, 3) OVER (
                           PARTITION BY CustomerID ORDER BY AsOfMonth
                       ) AS expected_quantity_lag_3,
                       Trailing3MonthSalesAverage,
                       AVG(NetSales) OVER (
                           PARTITION BY CustomerID ORDER BY AsOfMonth
                           ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                       ) AS expected_average,
                       Trailing3MonthQuantityAverage,
                       AVG(Quantity) OVER (
                           PARTITION BY CustomerID ORDER BY AsOfMonth
                           ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                       ) AS expected_quantity_average
                FROM feature_customer_monthly
            ) q
            WHERE SalesLag1Month IS DISTINCT FROM expected_lag
               OR SalesLag3Months IS DISTINCT FROM expected_lag_3
               OR QuantityLag1Month IS DISTINCT FROM expected_quantity_lag
               OR QuantityLag3Months IS DISTINCT FROM expected_quantity_lag_3
               OR Trailing3MonthSalesAverage IS DISTINCT FROM expected_average
               OR Trailing3MonthQuantityAverage IS DISTINCT FROM expected_quantity_average""",
        )
        trend_mismatches = {
            "sales_trend_features": scalar(
                con,
                """SELECT COUNT(*) FROM (
                    SELECT RecentSalesTrendPct, RecentQuantityTrendPct,
                           (AVG(NetSales) OVER (
                               PARTITION BY Region, Channel, Category
                               ORDER BY MonthStart
                               ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                           ) - AVG(NetSales) OVER (
                               PARTITION BY Region, Channel, Category
                               ORDER BY MonthStart
                               ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
                           )) / NULLIF(AVG(NetSales) OVER (
                               PARTITION BY Region, Channel, Category
                               ORDER BY MonthStart
                               ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
                           ), 0) AS expected_sales_trend,
                           (AVG(Quantity) OVER (
                               PARTITION BY Region, Channel, Category
                               ORDER BY MonthStart
                               ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                           ) - AVG(Quantity) OVER (
                               PARTITION BY Region, Channel, Category
                               ORDER BY MonthStart
                               ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
                           )) / NULLIF(AVG(Quantity) OVER (
                               PARTITION BY Region, Channel, Category
                               ORDER BY MonthStart
                               ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
                           ), 0) AS expected_quantity_trend
                    FROM feature_sales_monthly
                ) q
                WHERE RecentSalesTrendPct IS DISTINCT FROM expected_sales_trend
                   OR RecentQuantityTrendPct IS DISTINCT FROM expected_quantity_trend""",
            ),
            "customer_trend_and_asof_features": scalar(
                con,
                """SELECT COUNT(*) FROM (
                    SELECT CustomerID, AsOfMonth, AsOfDate, LastPurchaseDate,
                           DaysSinceLastPurchase, RecentSalesTrendPct,
                           RecentQuantityTrendPct, ActiveMonthsTrailing6,
                           PurchaseConsistencyTrailing6,
                           (AVG(NetSales) OVER (
                               PARTITION BY CustomerID ORDER BY AsOfMonth
                               ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                           ) - AVG(NetSales) OVER (
                               PARTITION BY CustomerID ORDER BY AsOfMonth
                               ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
                           )) / NULLIF(AVG(NetSales) OVER (
                               PARTITION BY CustomerID ORDER BY AsOfMonth
                               ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
                           ), 0) AS expected_sales_trend,
                           (AVG(Quantity) OVER (
                               PARTITION BY CustomerID ORDER BY AsOfMonth
                               ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
                           ) - AVG(Quantity) OVER (
                               PARTITION BY CustomerID ORDER BY AsOfMonth
                               ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
                           )) / NULLIF(AVG(Quantity) OVER (
                               PARTITION BY CustomerID ORDER BY AsOfMonth
                               ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
                           ), 0) AS expected_quantity_trend,
                           SUM(CASE WHEN TransactionCount > 0 THEN 1 ELSE 0 END) OVER (
                               PARTITION BY CustomerID ORDER BY AsOfMonth
                               ROWS BETWEEN 5 PRECEDING AND CURRENT ROW
                           ) AS expected_active_months_6,
                           COUNT(*) OVER (
                               PARTITION BY CustomerID ORDER BY AsOfMonth
                               ROWS BETWEEN 5 PRECEDING AND CURRENT ROW
                           ) AS expected_observed_months_6
                    FROM feature_customer_monthly
                ) q
                WHERE RecentSalesTrendPct IS DISTINCT FROM expected_sales_trend
                   OR RecentQuantityTrendPct IS DISTINCT FROM expected_quantity_trend
                   OR ActiveMonthsTrailing6 <> expected_active_months_6
                   OR PurchaseConsistencyTrailing6 IS DISTINCT FROM
                      expected_active_months_6::DOUBLE / expected_observed_months_6
                   OR LastPurchaseDate > AsOfDate
                   OR DaysSinceLastPurchase <>
                      date_diff('day', LastPurchaseDate, AsOfDate)""",
            ),
        }
        inventory_demand_mismatches = scalar(
            con,
            """WITH demand_by_month AS (
                   SELECT c.DistributorID, s.ProductID,
                          date_trunc('month', s."Date")::DATE AS MonthStart,
                          SUM(s.Qty) AS SalesQuantity
                   FROM fact_sales s JOIN dim_customer c USING (CustomerID)
                   GROUP BY 1, 2, 3
               ),
               expected AS (
                   SELECT i.SnapshotDate, i.DistributorID, i.ProductID,
                          COALESCE(SUM(d.SalesQuantity) FILTER (
                              WHERE d.MonthStart >=
                                  date_trunc('month', i.SnapshotDate) - INTERVAL '3 months'
                                AND d.MonthStart < date_trunc('month', i.SnapshotDate)
                          ), 0) AS recent_qty,
                          COALESCE(SUM(d.SalesQuantity) FILTER (
                              WHERE d.MonthStart >=
                                  date_trunc('month', i.SnapshotDate) - INTERVAL '6 months'
                                AND d.MonthStart <
                                  date_trunc('month', i.SnapshotDate) - INTERVAL '3 months'
                          ), 0) AS prior_qty
                   FROM fact_inventory i
                   LEFT JOIN demand_by_month d
                     ON d.DistributorID = i.DistributorID
                    AND d.ProductID = i.ProductID
                    AND d.MonthStart >=
                        date_trunc('month', i.SnapshotDate) - INTERVAL '6 months'
                    AND d.MonthStart < date_trunc('month', i.SnapshotDate)
                   GROUP BY 1, 2, 3
               )
               SELECT COUNT(*)
               FROM expected e JOIN feature_inventory_risk f USING (
                   SnapshotDate, DistributorID, ProductID
               )
               WHERE e.recent_qty <> f.Trailing3CompleteMonthsSalesQuantity
                  OR e.prior_qty <> f.Prior3CompleteMonthsSalesQuantity
                  OR f.SnapshotFreshnessDays <>
                     date_diff('day', f.SnapshotDate, ?)""",
            [as_of_date],
        )
        leakage_checks = {
            "sales_lag_or_window_mismatches": sales_lag_checks,
            "sales_trailing_average_mismatches": sales_window_mismatches,
            "customer_lag_or_window_mismatches": customer_window_mismatches,
            "trend_and_asof_mismatches": trend_mismatches,
            "inventory_demand_window_mismatches": inventory_demand_mismatches,
            "customer_future_asof_rows": customer_range[3],
            "target_source_referenced": False,
            "promotion_features_included": False,
        }
        if (
            any(sales_lag_checks.values())
            or sales_window_mismatches
            or customer_window_mismatches
            or any(trend_mismatches.values())
            or inventory_demand_mismatches
        ):
            raise ValueError(f"Leakage/window validation failed: {leakage_checks}")

        sales_reconciliation = con.execute(
            """SELECT
                   SUM(NetSales), SUM(Quantity), SUM(GrossMargin), SUM(DiscountAmount)
               FROM feature_sales_monthly"""
        ).fetchone()
        sales_source_totals = con.execute(
            """SELECT SUM(NetSales), SUM(Qty), SUM(GrossMargin), SUM(DiscountAmount)
               FROM fact_sales"""
        ).fetchone()
        customer_reconciliation = con.execute(
            """SELECT SUM(NetSales), SUM(Quantity), SUM(GrossMargin), SUM(DiscountAmount)
               FROM feature_customer_monthly"""
        ).fetchone()
        returns_reconciliation = con.execute(
            """SELECT SUM(ReturnAmount), SUM(ReturnQuantity)
               FROM feature_sales_monthly"""
        ).fetchone()
        returns_source_totals = con.execute(
            """SELECT SUM(ReturnAmount), SUM(ReturnQty)
               FROM fact_returns WHERE ReturnDate <= ?""",
            [max_month_end],
        ).fetchone()
        customer_returns_reconciliation = con.execute(
            """SELECT SUM(ReturnAmount), SUM(ReturnQuantity)
               FROM feature_customer_monthly"""
        ).fetchone()
        inventory_reconciliation = con.execute(
            """WITH source_totals AS (
                   SELECT SnapshotDate, SUM(OnHandQty) AS on_hand,
                          SUM(InTransitQty) AS in_transit,
                          SUM(ExpiredQty) AS expired,
                          COUNT(*) FILTER (WHERE OnHandQty < ReorderPoint) AS exceptions
                   FROM fact_inventory GROUP BY SnapshotDate
               ),
               feature_totals AS (
                   SELECT SnapshotDate, SUM(OnHandQuantity) AS on_hand,
                          SUM(InTransitQuantity) AS in_transit,
                          SUM(ExpiredQuantity) AS expired,
                          SUM(CurrentReorderException) AS exceptions
                   FROM feature_inventory_risk GROUP BY SnapshotDate
               )
               SELECT COUNT(*) FILTER (
                   WHERE s.SnapshotDate IS NULL OR f.SnapshotDate IS NULL
                      OR ABS(s.on_hand - f.on_hand) > 0
                      OR ABS(s.in_transit - f.in_transit) > 0
                      OR ABS(s.expired - f.expired) > 0
                      OR s.exceptions <> f.exceptions
               )
               FROM source_totals s FULL OUTER JOIN feature_totals f USING (SnapshotDate)"""
        ).fetchone()[0]

        reconciliations = {
            "sales_monthly_vs_fact_sales": {
                "feature": list(sales_reconciliation),
                "source": list(sales_source_totals),
                "absolute_differences": [
                    abs(float(a or 0) - float(b or 0))
                    for a, b in zip(sales_reconciliation, sales_source_totals)
                ],
            },
            "customer_monthly_vs_fact_sales": {
                "feature": list(customer_reconciliation),
                "source": list(sales_source_totals),
                "absolute_differences": [
                    abs(float(a or 0) - float(b or 0))
                    for a, b in zip(customer_reconciliation, sales_source_totals)
                ],
            },
            "returns_through_latest_sales_month": {
                "feature": list(returns_reconciliation),
                "customer_feature": list(customer_returns_reconciliation),
                "source": list(returns_source_totals),
                "absolute_differences": [
                    abs(float(a or 0) - float(b or 0))
                    for a, b in zip(returns_reconciliation, returns_source_totals)
                ],
                "customer_feature_absolute_differences": [
                    abs(float(a or 0) - float(b or 0))
                    for a, b in zip(customer_returns_reconciliation, returns_source_totals)
                ],
                "excluded_return_rows_after_cutoff": con.execute(
                    "SELECT COUNT(*) FROM fact_returns WHERE ReturnDate > ?",
                    [max_month_end],
                ).fetchone()[0],
            },
            "inventory_per_snapshot_vs_fact_inventory": {
                "mismatched_snapshot_dates": inventory_reconciliation,
                "snapshot_dates": scalar(
                    con,
                    "SELECT COUNT(DISTINCT SnapshotDate) FROM feature_inventory_risk",
                ),
            },
        }
        if any(
            difference > TOLERANCE
            for section in (
                reconciliations["sales_monthly_vs_fact_sales"],
                reconciliations["customer_monthly_vs_fact_sales"],
                reconciliations["returns_through_latest_sales_month"],
            )
            for difference in (
                section["absolute_differences"]
                + section.get("customer_feature_absolute_differences", [])
            )
        ) or inventory_reconciliation:
            raise ValueError(f"Source reconciliation failed: {reconciliations}")

        inventory_coverage = con.execute(
            """SELECT MIN(SnapshotDate), MAX(SnapshotDate),
                      COUNT(DISTINCT SnapshotDate), COUNT(*),
                      COUNT(*) FILTER (WHERE InventoryCoverageDaysProxy IS NULL)
               FROM feature_inventory_risk"""
        ).fetchone()
        customer_history = con.execute(
            """SELECT MIN(AsOfMonth), MAX(AsOfMonth), COUNT(DISTINCT CustomerID),
                      MIN(DaysSinceLastPurchase), MAX(DaysSinceLastPurchase)
               FROM feature_customer_monthly"""
        ).fetchone()
        report = {
            "built_at": date.today().isoformat(),
            "as_of_date": as_of_date.isoformat(),
            "source_database": str(source_db),
            "feature_database": str(feature_db),
            "feature_tables": profiles,
            "keys": key_checks,
            "sales_history": {
                "first_fact_date": first_sales_date.isoformat(),
                "latest_fact_date": latest_sales_date.isoformat(),
                "first_month": first_sales_month.isoformat(),
                "latest_month": latest_sales_month.isoformat(),
                "calendar_complete_months": len(sales_months),
                "month_completeness_basis": (
                    "One source file per month and source fact dates span the "
                    "first through final calendar day; no independent ingestion "
                    "manifest is available."
                ),
                "monthly_rows": [
                    {
                        "month": row[0].isoformat(),
                        "transactions": row[1],
                        "source_files": row[2],
                        "first_fact_date": row[3].isoformat(),
                        "last_fact_date": row[4].isoformat(),
                    }
                    for row in sales_months
                ],
                "fact_sales_rows": sales_rows,
            },
            "customer_history": {
                "dimension_customers": dimension_customers,
                "customers_with_sales": source_sales_customers,
                "customers_without_sales": customers_without_sales,
                "feature_first_asof_month": customer_history[0].isoformat(),
                "feature_latest_asof_month": customer_history[1].isoformat(),
                "feature_customer_count": customer_history[2],
                "min_days_since_last_purchase": customer_history[3],
                "max_days_since_last_purchase": customer_history[4],
                "sales_before_dimension_join_date_transactions": sales_before_join_date[0],
                "customers_with_sales_before_join_date": sales_before_join_date[1],
                "join_date_used_as_feature": False,
            },
            "inventory_history": {
                "first_snapshot": inventory_coverage[0].isoformat(),
                "latest_snapshot": inventory_coverage[1].isoformat(),
                "snapshot_count": inventory_coverage[2],
                "feature_rows": inventory_coverage[3],
                "coverage_proxy_null_rows": inventory_coverage[4],
                "freshness_as_of": as_of_date.isoformat(),
            },
            "null_patterns": {
                table: profile["nulls"] for table, profile in profiles.items()
            },
            "invalid_values": invalid_values,
            "leakage_checks": leakage_checks,
            "reconciliations": reconciliations,
            "limitations": [
                "JoinDate is excluded because fact sales precede it for some customers.",
                "Return features stop at the latest complete sales month; later returns are not future information for those as-of rows.",
                "Inventory coverage is a demand-based proxy, not a stockout prediction; lead time/order cadence and lot expiry are unavailable.",
                "Distributor sales demand uses the current customer-to-distributor mapping because historical assignment data is unavailable.",
                "Promotion features and targets are intentionally excluded from predictor features.",
            ],
        }

        with tempfile.TemporaryDirectory(
            prefix=".feature-build-", dir=OUTPUT_DIR
        ) as stage:
            for table in FEATURE_TABLES:
                target = Path(stage) / f"{table}.csv"
                target_sql = str(target).replace("'", "''")
                con.execute(
                    f"COPY {table} TO '{target_sql}' "
                    "(HEADER, DELIMITER ',', FORMAT CSV)"
                )
            report_path = Path(stage) / "feature_validation.json"
            report_path.write_text(
                json.dumps(report, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            con.execute("COMMIT")

            for table in FEATURE_TABLES:
                os.replace(
                    Path(stage) / f"{table}.csv",
                    OUTPUT_DIR / f"{table}.csv",
                )
            os.replace(report_path, OUTPUT_DIR / "feature_validation.json")

        return report
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
    parser.add_argument(
        "--source-db",
        type=Path,
        default=SOURCE_DB,
        help="Validated analytical DuckDB source (read-only).",
    )
    parser.add_argument(
        "--feature-db",
        type=Path,
        default=FEATURE_DB,
        help="Separate DuckDB file that will hold the feature tables.",
    )
    parser.add_argument(
        "--as-of-date",
        type=parse_date,
        default=date.today(),
        help="Snapshot freshness reference date (YYYY-MM-DD; defaults to today).",
    )
    args = parser.parse_args()
    result = run_build(args.source_db, args.feature_db, args.as_of_date)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
