import duckdb
import os
from pathlib import Path

DB_PATH = Path(
    os.environ.get(
        "FMCG_DB_PATH",
        "database/fmcg_analytics_main.duckdb",
    )
)
SQL_PATH = Path(".venv/SQL/sql/04_model_views.sql")

con = duckdb.connect(str(DB_PATH))

print("Connected to:", DB_PATH)

tables = {
    "fact_sales": "processed/fact_sales.csv",
    "fact_returns": "processed/fact_returns.csv",
    "fact_target": "processed/fact_target.csv",
    "fact_inventory": "processed/fact_inventory.csv",
    "dim_customer": "processed/dim_customer.csv",
    "dim_product": "processed/dim_product.csv",
    "dim_salesforce": "processed/dim_salesforce.csv",
    "dim_promotion": "processed/dim_promotion.csv",
    "dim_date": "processed/dim_date.csv",
    "dim_distributor": "processed/dim_distributor.csv",
}

for table_name, file_path in tables.items():

    con.execute(f"""
        CREATE OR REPLACE TABLE {table_name} AS
        SELECT *
        FROM read_csv_auto('{file_path}')
    """)

    count = con.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    ).fetchone()[0]

    print(f"{table_name}: {count:,} rows")

con.execute(SQL_PATH.read_text(encoding="utf-8"))
con.execute("""
    CREATE OR REPLACE TABLE fact_promotion_attribution AS
    SELECT * FROM vw_sales_promotion_attributed
""")
con.execute("""
    COPY fact_promotion_attribution
    TO 'processed/fact_promotion_attribution.csv'
    (HEADER, DELIMITER ',')
""")
promotion_attribution_count = con.execute(
    "SELECT COUNT(*) FROM fact_promotion_attribution"
).fetchone()[0]
print(f"fact_promotion_attribution: {promotion_attribution_count:,} rows")
print("Analytical model views created.")

con.close()

print("Database build completed.")