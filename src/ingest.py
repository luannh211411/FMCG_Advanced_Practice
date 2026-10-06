from pathlib import Path
import pandas as pd


DATA_PATH = Path("data")


def load_monthly_sales():

    sales_files = sorted(
        (DATA_PATH / "sales").glob("sales_20*.csv")
    )

    sales_list = []

    for file in sales_files:

        df = pd.read_csv(file)

        df["SourceFile"] = file.name

        sales_list.append(df)

    sales = pd.concat(
        sales_list,
        ignore_index=True
    )

    return sales


def load_source_tables():

    tables = {
        "customers": pd.read_csv(
            DATA_PATH / "customers/dim_customer.csv"
        ),

        "products": pd.read_csv(
            DATA_PATH / "products/dim_product.csv"
        ),

        "targets": pd.read_csv(
            DATA_PATH / "targets/fact_target.csv"
        ),

        "inventory": pd.read_csv(
            DATA_PATH / "inventory/fact_inventory_snapshot.csv"
        ),

        "salesforce": pd.read_csv(
            DATA_PATH / "salesforce/dim_salesforce.csv"
        ),

        "promotions": pd.read_csv(
            DATA_PATH / "promotions/dim_promotion.csv"
        ),

        "returns": pd.read_csv(
            DATA_PATH / "sales/sales_returns.csv"
        )
    }

    return tables