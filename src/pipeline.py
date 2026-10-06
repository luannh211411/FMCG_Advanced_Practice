from pathlib import Path

import pandas as pd

from ingest import (
    load_monthly_sales,
    load_source_tables
)

from validate import validate_model_tables, validate_sales
from transform import (
    transform_date_dimension,
    transform_distributor_dimension,
    transform_sales,
)


OUTPUT_PATH = Path("processed")

OUTPUT_PATH.mkdir(
    exist_ok=True
)


print("Starting FMCG data pipeline...")


# 1. INGEST

sales = load_monthly_sales()

tables = load_source_tables()

customers = tables["customers"]
products = tables["products"]
returns = tables["returns"]
targets = tables["targets"]
inventory = tables["inventory"]
salesforce = tables["salesforce"]
promotions = tables["promotions"]


print(
    f"Loaded {len(sales):,} sales transactions"
)


# 2. VALIDATE

errors = validate_sales(
    sales,
    customers,
    products
)


if errors:

    print("\nDATA VALIDATION FAILED")

    for error in errors:
        print(" -", error)

    raise ValueError(
        "Pipeline stopped due to data quality errors."
    )


print("Data validation PASSED")


# 3. TRANSFORM

fact_sales = transform_sales(
    sales
)

all_dates = pd.concat(
    [
        pd.to_datetime(sales["Date"]),
        pd.to_datetime(returns["ReturnDate"]),
        pd.to_datetime(inventory["SnapshotDate"]),
        pd.to_datetime(targets["Month"]),
    ]
)
date_dimension = transform_date_dimension(
    all_dates.min().date(),
    max(all_dates.max(), pd.Timestamp("2026-12-31")).date(),
)
distributors = transform_distributor_dimension(customers, inventory)

model_errors = validate_model_tables(
    fact_sales,
    customers,
    products,
    returns,
    targets,
    inventory,
    salesforce,
    promotions,
    date_dimension,
    distributors,
)

if model_errors:
    print("\nMODEL VALIDATION FAILED")
    for error in model_errors:
        print(" -", error)
    raise ValueError("Pipeline stopped due to analytical model errors.")

print("Analytical model validation PASSED")


# 4. OUTPUT

fact_sales.to_csv(
    OUTPUT_PATH / "fact_sales.csv",
    index=False
)

customers.to_csv(
    OUTPUT_PATH / "dim_customer.csv",
    index=False
)

products.to_csv(
    OUTPUT_PATH / "dim_product.csv",
    index=False
)

tables["targets"].to_csv(
    OUTPUT_PATH / "fact_target.csv",
    index=False
)

tables["inventory"].to_csv(
    OUTPUT_PATH / "fact_inventory.csv",
    index=False
)

tables["returns"].to_csv(
    OUTPUT_PATH / "fact_returns.csv",
    index=False
)

tables["salesforce"].to_csv(
    OUTPUT_PATH / "dim_salesforce.csv",
    index=False
)

tables["promotions"].to_csv(
    OUTPUT_PATH / "dim_promotion.csv",
    index=False
)

date_dimension.to_csv(
    OUTPUT_PATH / "dim_date.csv",
    index=False,
)

distributors.to_csv(
    OUTPUT_PATH / "dim_distributor.csv",
    index=False,
)


print("\nPipeline completed successfully.")

print(
    f"Processed sales rows: {len(fact_sales):,}"
)