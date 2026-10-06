import pandas as pd


def validate_sales(
    sales,
    customers,
    products
):

    errors = []

    # Transaction ID must be unique
    duplicate_transactions = (
        sales["TransactionID"]
        .duplicated()
        .sum()
    )

    if duplicate_transactions > 0:
        errors.append(
            f"Duplicate TransactionID: {duplicate_transactions}"
        )


    # Customer must exist
    invalid_customers = (
        ~sales["CustomerID"]
        .isin(customers["CustomerID"])
    ).sum()

    if invalid_customers > 0:
        errors.append(
            f"Invalid CustomerID: {invalid_customers}"
        )


    # Product must exist
    invalid_products = (
        ~sales["ProductID"]
        .isin(products["ProductID"])
    ).sum()

    if invalid_products > 0:
        errors.append(
            f"Invalid ProductID: {invalid_products}"
        )


    # Net Sales formula
    net_sales_error = (
        sales["GrossSales"]
        - sales["DiscountAmount"]
        - sales["NetSales"]
    ).abs()

    invalid_net_sales = (
        net_sales_error > 1
    ).sum()

    if invalid_net_sales > 0:
        errors.append(
            f"Invalid NetSales calculation: {invalid_net_sales}"
        )


    # Gross Margin formula
    margin_error = (
        sales["NetSales"]
        - sales["COGS"]
        - sales["GrossMargin"]
    ).abs()

    invalid_margin = (
        margin_error > 1
    ).sum()

    if invalid_margin > 0:
        errors.append(
            f"Invalid GrossMargin calculation: {invalid_margin}"
        )


    return errors


def validate_model_tables(
    sales,
    customers,
    products,
    returns,
    targets,
    inventory,
    salesforce,
    promotions,
    date_dimension,
    distributors,
):
    errors = []

    unique_keys = {
        "TransactionID": (sales, ["TransactionID"]),
        "CustomerID": (customers, ["CustomerID"]),
        "ProductID": (products, ["ProductID"]),
        "ReturnID": (returns, ["ReturnID"]),
        "SalesRepID": (salesforce, ["SalesRepID"]),
        "PromotionID": (promotions, ["PromotionID"]),
        "Date": (date_dimension, ["Date"]),
        "DistributorID": (distributors, ["DistributorID"]),
        "Target grain": (
            targets,
            ["Month", "Region", "Channel", "Category"],
        ),
        "Inventory grain": (
            inventory,
            ["SnapshotDate", "DistributorID", "ProductID"],
        ),
    }

    for name, (table, key) in unique_keys.items():
        if table[key].isna().any(axis=1).sum() > 0:
            errors.append(f"Null values in {name} key")
        duplicates = table.duplicated(key).sum()
        if duplicates > 0:
            errors.append(f"Duplicate {name} key rows: {duplicates}")

    foreign_keys = {
        "sales CustomerID": (sales, "CustomerID", customers, "CustomerID"),
        "sales ProductID": (sales, "ProductID", products, "ProductID"),
        "returns TransactionID": (returns, "TransactionID", sales, "TransactionID"),
        "returns CustomerID": (returns, "CustomerID", customers, "CustomerID"),
        "returns ProductID": (returns, "ProductID", products, "ProductID"),
        "customer SalesRepID": (customers, "SalesRepID", salesforce, "SalesRepID"),
        "inventory DistributorID": (inventory, "DistributorID", distributors, "DistributorID"),
        "inventory ProductID": (inventory, "ProductID", products, "ProductID"),
        "sales Date": (sales.assign(Date=pd.to_datetime(sales["Date"]).dt.normalize()), "Date", date_dimension, "Date"),
        "returns ReturnDate": (returns.assign(ReturnDate=pd.to_datetime(returns["ReturnDate"]).dt.normalize()), "ReturnDate", date_dimension, "Date"),
        "inventory SnapshotDate": (inventory.assign(SnapshotDate=pd.to_datetime(inventory["SnapshotDate"]).dt.normalize()), "SnapshotDate", date_dimension, "Date"),
        "target Month": (targets.assign(Month=pd.to_datetime(targets["Month"]).dt.normalize()), "Month", date_dimension, "MonthStart"),
    }

    for name, (child, child_key, parent, parent_key) in foreign_keys.items():
        missing = (~child[child_key].isin(parent[parent_key])).sum()
        if missing > 0:
            errors.append(f"Invalid {name}: {missing}")

    if len(sales.merge(customers, on="CustomerID", how="left")) != len(sales):
        errors.append("Sales-to-customer join multiplied fact rows")
    if len(sales.merge(products, on="ProductID", how="left")) != len(sales):
        errors.append("Sales-to-product join multiplied fact rows")
    if (pd.to_datetime(promotions["EndDate"]) < pd.to_datetime(promotions["StartDate"])).any():
        errors.append("Promotion EndDate precedes StartDate")

    return errors