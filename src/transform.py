import pandas as pd


def transform_sales(sales):

    df = sales.copy()

    # Convert date
    df["Date"] = pd.to_datetime(
        df["Date"]
    )

    # Add useful time attributes
    df["Year"] = df["Date"].dt.year

    df["MonthNumber"] = (
        df["Date"].dt.month
    )

    df["YearMonth"] = (
        df["Date"]
        .dt.to_period("M")
        .astype(str)
    )

    return df


def transform_date_dimension(start_date, end_date):
    dates = pd.date_range(start=start_date, end=end_date, freq="D")

    return pd.DataFrame(
        {
            "Date": dates,
            "Year": dates.year,
            "Quarter": dates.quarter,
            "MonthNumber": dates.month,
            "MonthName": dates.strftime("%B"),
            "YearMonth": dates.to_period("M").astype(str),
            "MonthStart": dates.to_period("M").to_timestamp(),
        }
    )


def transform_distributor_dimension(customers, inventory):
    customer_ids = customers[["DistributorID"]]
    inventory_ids = inventory[["DistributorID"]]
    distributor_ids = pd.concat(
        [customer_ids, inventory_ids],
        ignore_index=True,
    ).drop_duplicates()

    return distributor_ids.sort_values("DistributorID").reset_index(drop=True)