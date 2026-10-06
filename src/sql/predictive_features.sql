CREATE OR REPLACE TABLE feature_sales_monthly AS
WITH sales_bounds AS (
    SELECT
        date_trunc('month', MIN("Date"))::DATE AS first_month,
        date_trunc('month', MAX("Date"))::DATE AS last_month
    FROM fact_sales
),
calendar AS (
    SELECT
        d.MonthStart,
        d.Year,
        d.Quarter,
        d.MonthNumber,
        d.MonthName,
        row_number() OVER (ORDER BY d.MonthStart)::BIGINT AS TimeIndex
    FROM (
        SELECT DISTINCT MonthStart, Year, Quarter, MonthNumber, MonthName
        FROM dim_date
    ) d
    CROSS JOIN sales_bounds b
    WHERE d.MonthStart BETWEEN b.first_month AND b.last_month
),
observed_combinations AS (
    SELECT DISTINCT c.Region, c.Channel, p.Category
    FROM fact_sales s
    JOIN dim_customer c USING (CustomerID)
    JOIN dim_product p USING (ProductID)
),
sales_by_month AS (
    SELECT
        date_trunc('month', s."Date")::DATE AS MonthStart,
        c.Region,
        c.Channel,
        p.Category,
        SUM(s.NetSales) AS NetSales,
        SUM(s.Qty) AS Quantity,
        SUM(s.GrossMargin) AS GrossMargin,
        SUM(s.GrossSales) AS GrossSales,
        SUM(s.DiscountAmount) AS DiscountAmount,
        COUNT(DISTINCT s.CustomerID)::BIGINT AS ActiveCustomers,
        COUNT(DISTINCT s.TransactionID)::BIGINT AS TransactionCount
    FROM fact_sales s
    JOIN dim_customer c USING (CustomerID)
    JOIN dim_product p USING (ProductID)
    GROUP BY 1, 2, 3, 4
),
returns_by_month AS (
    SELECT
        date_trunc('month', r.ReturnDate)::DATE AS MonthStart,
        c.Region,
        c.Channel,
        p.Category,
        SUM(r.ReturnAmount) AS ReturnAmount,
        SUM(r.ReturnQty) AS ReturnQuantity
    FROM fact_returns r
    JOIN dim_customer c USING (CustomerID)
    JOIN dim_product p USING (ProductID)
    GROUP BY 1, 2, 3, 4
),
scaffold AS (
    SELECT
        cal.MonthStart,
        cal.Year,
        cal.Quarter,
        cal.MonthNumber,
        cal.MonthName,
        cal.TimeIndex,
        combo.Region,
        combo.Channel,
        combo.Category,
        COALESCE(s.NetSales, 0) AS NetSales,
        COALESCE(s.Quantity, 0) AS Quantity,
        COALESCE(s.GrossMargin, 0) AS GrossMargin,
        COALESCE(s.GrossSales, 0) AS GrossSales,
        COALESCE(s.DiscountAmount, 0) AS DiscountAmount,
        COALESCE(s.ActiveCustomers, 0) AS ActiveCustomers,
        COALESCE(s.TransactionCount, 0) AS TransactionCount,
        COALESCE(r.ReturnAmount, 0) AS ReturnAmount,
        COALESCE(r.ReturnQuantity, 0) AS ReturnQuantity
    FROM calendar cal
    CROSS JOIN observed_combinations combo
    LEFT JOIN sales_by_month s
        ON s.MonthStart = cal.MonthStart
        AND s.Region = combo.Region
        AND s.Channel = combo.Channel
        AND s.Category = combo.Category
    LEFT JOIN returns_by_month r
        ON r.MonthStart = cal.MonthStart
        AND r.Region = combo.Region
        AND r.Channel = combo.Channel
        AND r.Category = combo.Category
),
windowed AS (
    SELECT
        *,
        GrossMargin / NULLIF(NetSales, 0) AS GrossMarginPct,
        DiscountAmount / NULLIF(GrossSales, 0) AS DiscountPct,
        ReturnAmount / NULLIF(NetSales, 0) AS ReturnRate,
        LAG(NetSales, 1) OVER series AS SalesLag1Month,
        LAG(NetSales, 3) OVER series AS SalesLag3Months,
        LAG(NetSales, 12) OVER series AS SalesLag12Months,
        LAG(Quantity, 1) OVER series AS QuantityLag1Month,
        LAG(Quantity, 3) OVER series AS QuantityLag3Months,
        AVG(NetSales) OVER (
            PARTITION BY Region, Channel, Category
            ORDER BY MonthStart ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ) AS Trailing3MonthSalesAverage,
        AVG(Quantity) OVER (
            PARTITION BY Region, Channel, Category
            ORDER BY MonthStart ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ) AS Trailing3MonthQuantityAverage,
        AVG(NetSales) OVER (
            PARTITION BY Region, Channel, Category
            ORDER BY MonthStart ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
        ) AS Prior3MonthSalesAverage,
        AVG(Quantity) OVER (
            PARTITION BY Region, Channel, Category
            ORDER BY MonthStart ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
        ) AS Prior3MonthQuantityAverage
    FROM scaffold
    WINDOW series AS (
        PARTITION BY Region, Channel, Category
        ORDER BY MonthStart
    )
)
SELECT
    MonthStart,
    Year,
    Quarter,
    MonthNumber,
    MonthName,
    TimeIndex,
    Region,
    Channel,
    Category,
    NetSales,
    Quantity,
    GrossMargin,
    GrossMarginPct,
    ActiveCustomers,
    TransactionCount,
    GrossSales,
    DiscountAmount,
    DiscountPct,
    ReturnAmount,
    ReturnQuantity,
    ReturnRate,
    SalesLag1Month,
    SalesLag3Months,
    SalesLag12Months,
    QuantityLag1Month,
    QuantityLag3Months,
    Trailing3MonthSalesAverage,
    Trailing3MonthQuantityAverage,
    (Trailing3MonthSalesAverage - Prior3MonthSalesAverage)
        / NULLIF(Prior3MonthSalesAverage, 0) AS RecentSalesTrendPct,
    (Trailing3MonthQuantityAverage - Prior3MonthQuantityAverage)
        / NULLIF(Prior3MonthQuantityAverage, 0) AS RecentQuantityTrendPct
FROM windowed;

CREATE OR REPLACE TABLE feature_customer_monthly AS
WITH sales_bounds AS (
    SELECT
        date_trunc('month', MIN("Date"))::DATE AS first_month,
        date_trunc('month', MAX("Date"))::DATE AS last_month
    FROM fact_sales
),
calendar AS (
    SELECT DISTINCT MonthStart
    FROM dim_date
    CROSS JOIN sales_bounds b
    WHERE MonthStart BETWEEN b.first_month AND b.last_month
),
customer_first_month AS (
    SELECT CustomerID, MIN(date_trunc('month', "Date"))::DATE AS FirstSalesMonth
    FROM fact_sales
    GROUP BY CustomerID
),
sales_by_customer_month AS (
    SELECT
        s.CustomerID,
        date_trunc('month', s."Date")::DATE AS AsOfMonth,
        SUM(s.NetSales) AS NetSales,
        SUM(s.Qty) AS Quantity,
        SUM(s.GrossMargin) AS GrossMargin,
        SUM(s.GrossSales) AS GrossSales,
        SUM(s.DiscountAmount) AS DiscountAmount,
        COUNT(DISTINCT s.TransactionID)::BIGINT AS TransactionCount,
        COUNT(DISTINCT s."Date")::BIGINT AS ActiveSalesDays,
        MAX(s."Date") AS LastPurchaseDateInMonth
    FROM fact_sales s
    GROUP BY 1, 2
),
returns_by_customer_month AS (
    SELECT
        r.CustomerID,
        date_trunc('month', r.ReturnDate)::DATE AS AsOfMonth,
        SUM(r.ReturnAmount) AS ReturnAmount,
        SUM(r.ReturnQty) AS ReturnQuantity
    FROM fact_returns r
    GROUP BY 1, 2
),
purchase_days AS (
    SELECT CustomerID, "Date" AS PurchaseDate
    FROM fact_sales
    GROUP BY CustomerID, "Date"
),
purchase_intervals AS (
    SELECT
        CustomerID,
        PurchaseDate,
        date_diff(
            'day',
            LAG(PurchaseDate) OVER (
                PARTITION BY CustomerID ORDER BY PurchaseDate
            ),
            PurchaseDate
        ) AS IntervalDays
    FROM purchase_days
),
intervals_by_customer_month AS (
    SELECT
        CustomerID,
        date_trunc('month', PurchaseDate)::DATE AS AsOfMonth,
        SUM(IntervalDays) AS IntervalDaysSum,
        COUNT(IntervalDays)::BIGINT AS IntervalCount
    FROM purchase_intervals
    GROUP BY 1, 2
),
scaffold AS (
    SELECT
        c.CustomerID,
        cal.MonthStart AS AsOfMonth,
        COALESCE(s.NetSales, 0) AS NetSales,
        COALESCE(s.Quantity, 0) AS Quantity,
        COALESCE(s.GrossMargin, 0) AS GrossMargin,
        COALESCE(s.GrossSales, 0) AS GrossSales,
        COALESCE(s.DiscountAmount, 0) AS DiscountAmount,
        COALESCE(s.TransactionCount, 0) AS TransactionCount,
        COALESCE(s.ActiveSalesDays, 0) AS ActiveSalesDays,
        COALESCE(r.ReturnAmount, 0) AS ReturnAmount,
        COALESCE(r.ReturnQuantity, 0) AS ReturnQuantity,
        s.LastPurchaseDateInMonth,
        COALESCE(i.IntervalDaysSum, 0) AS IntervalDaysSum,
        COALESCE(i.IntervalCount, 0) AS IntervalCount
    FROM customer_first_month c
    JOIN calendar cal ON cal.MonthStart >= c.FirstSalesMonth
    LEFT JOIN sales_by_customer_month s
        ON s.CustomerID = c.CustomerID AND s.AsOfMonth = cal.MonthStart
    LEFT JOIN returns_by_customer_month r
        ON r.CustomerID = c.CustomerID AND r.AsOfMonth = cal.MonthStart
    LEFT JOIN intervals_by_customer_month i
        ON i.CustomerID = c.CustomerID AND i.AsOfMonth = cal.MonthStart
),
windowed AS (
    SELECT
        *,
        last_day(AsOfMonth) AS AsOfDate,
        GrossMargin / NULLIF(NetSales, 0) AS GrossMarginPct,
        DiscountAmount / NULLIF(GrossSales, 0) AS DiscountPct,
        ReturnAmount / NULLIF(NetSales, 0) AS ReturnRate,
        CASE WHEN TransactionCount > 0 THEN 1 ELSE 0 END AS ActiveMonth,
        LAG(NetSales, 1) OVER customer_series AS SalesLag1Month,
        LAG(NetSales, 3) OVER customer_series AS SalesLag3Months,
        LAG(Quantity, 1) OVER customer_series AS QuantityLag1Month,
        LAG(Quantity, 3) OVER customer_series AS QuantityLag3Months,
        AVG(NetSales) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ) AS Trailing3MonthSalesAverage,
        AVG(Quantity) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ) AS Trailing3MonthQuantityAverage,
        AVG(NetSales) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
        ) AS Prior3MonthSalesAverage,
        AVG(Quantity) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 5 PRECEDING AND 3 PRECEDING
        ) AS Prior3MonthQuantityAverage,
        SUM(NetSales) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
        ) AS Trailing12MonthSales,
        SUM(ActiveMonth) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ) AS ActiveMonthsTrailing3,
        SUM(ActiveMonth) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 5 PRECEDING AND CURRENT ROW
        ) AS ActiveMonthsTrailing6,
        SUM(ActiveMonth) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
        ) AS ActiveMonthsTrailing12,
        SUM(TransactionCount) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
        ) AS PurchaseFrequencyTrailing3Months,
        SUM(TransactionCount) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
        ) AS PurchaseFrequencyTrailing12Months,
        SUM(IntervalDaysSum) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
        ) AS IntervalDaysSumTrailing12Months,
        SUM(IntervalCount) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 11 PRECEDING AND CURRENT ROW
        ) AS IntervalCountTrailing12Months,
        COUNT(*) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN 5 PRECEDING AND CURRENT ROW
        ) AS MonthsObservedTrailing6,
        MAX(LastPurchaseDateInMonth) OVER (
            PARTITION BY CustomerID ORDER BY AsOfMonth
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS LastPurchaseDate
    FROM scaffold
    WINDOW customer_series AS (
        PARTITION BY CustomerID ORDER BY AsOfMonth
    )
)
SELECT
    CustomerID,
    AsOfMonth,
    AsOfDate,
    NetSales,
    Quantity,
    GrossMargin,
    GrossMarginPct,
    TransactionCount,
    ActiveSalesDays,
    DiscountAmount,
    DiscountPct,
    ReturnAmount,
    ReturnQuantity,
    ReturnRate,
    ActiveMonth,
    LastPurchaseDate,
    date_diff('day', LastPurchaseDate, AsOfDate)::BIGINT AS DaysSinceLastPurchase,
    SalesLag1Month,
    SalesLag3Months,
    QuantityLag1Month,
    QuantityLag3Months,
    Trailing3MonthSalesAverage,
    Trailing3MonthQuantityAverage,
    (Trailing3MonthSalesAverage - Prior3MonthSalesAverage)
        / NULLIF(Prior3MonthSalesAverage, 0) AS RecentSalesTrendPct,
    (Trailing3MonthQuantityAverage - Prior3MonthQuantityAverage)
        / NULLIF(Prior3MonthQuantityAverage, 0) AS RecentQuantityTrendPct,
    Trailing12MonthSales,
    ActiveMonthsTrailing3,
    ActiveMonthsTrailing6,
    ActiveMonthsTrailing12,
    PurchaseFrequencyTrailing3Months,
    PurchaseFrequencyTrailing12Months,
    CAST(ActiveMonthsTrailing12 AS DOUBLE)
        / NULLIF(LEAST(12, date_diff('month', MIN(AsOfMonth) OVER (PARTITION BY CustomerID), AsOfMonth) + 1), 0)
        AS ActiveMonthConsistencyTrailing12,
    CAST(ActiveMonthsTrailing6 AS DOUBLE)
        / NULLIF(MonthsObservedTrailing6, 0) AS PurchaseConsistencyTrailing6,
    Trailing12MonthSales / NULLIF(ActiveMonthsTrailing12, 0)
        AS SalesPerActiveMonthTrailing12,
    IntervalDaysSumTrailing12Months
        / NULLIF(IntervalCountTrailing12Months, 0)
        AS AveragePurchaseIntervalDaysTrailing12
FROM windowed;

CREATE OR REPLACE TABLE feature_inventory_risk AS
WITH params AS (
    SELECT CAST(getvariable('feature_as_of_date') AS DATE) AS AsOfDate
),
demand_by_month AS (
    SELECT
        c.DistributorID,
        s.ProductID,
        date_trunc('month', s."Date")::DATE AS MonthStart,
        SUM(s.Qty) AS SalesQuantity
    FROM fact_sales s
    JOIN dim_customer c USING (CustomerID)
    GROUP BY 1, 2, 3
),
snapshot_demand AS (
    SELECT
        i.SnapshotDate,
        i.DistributorID,
        i.ProductID,
        i.OnHandQty,
        i.InTransitQty,
        i.ReorderPoint,
        i.ExpiredQty,
        p.AsOfDate,
        date_trunc('month', i.SnapshotDate)::DATE AS SnapshotMonth,
        COALESCE(SUM(d.SalesQuantity) FILTER (
            WHERE d.MonthStart >= date_trunc('month', i.SnapshotDate) - INTERVAL '3 months'
              AND d.MonthStart < date_trunc('month', i.SnapshotDate)
        ), 0) AS Trailing3CompleteMonthsSalesQuantity,
        COALESCE(SUM(d.SalesQuantity) FILTER (
            WHERE d.MonthStart >= date_trunc('month', i.SnapshotDate) - INTERVAL '6 months'
              AND d.MonthStart < date_trunc('month', i.SnapshotDate) - INTERVAL '3 months'
        ), 0) AS Prior3CompleteMonthsSalesQuantity
    FROM fact_inventory i
    CROSS JOIN params p
    LEFT JOIN demand_by_month d
        ON d.DistributorID = i.DistributorID
        AND d.ProductID = i.ProductID
        AND d.MonthStart >= date_trunc('month', i.SnapshotDate) - INTERVAL '6 months'
        AND d.MonthStart < date_trunc('month', i.SnapshotDate)
    GROUP BY
        i.SnapshotDate, i.DistributorID, i.ProductID, i.OnHandQty,
        i.InTransitQty, i.ReorderPoint, i.ExpiredQty, p.AsOfDate
),
derived AS (
    SELECT
        *,
        (OnHandQty + InTransitQty)::BIGINT AS AvailableInventoryQty,
        date_diff(
            'day',
            SnapshotMonth - INTERVAL '3 months',
            SnapshotMonth
        ) AS TrailingWindowDays,
        Trailing3CompleteMonthsSalesQuantity
            / NULLIF(date_diff(
                'day',
                SnapshotMonth - INTERVAL '3 months',
                SnapshotMonth
            ), 0) AS SalesVelocityQuantityPerDay,
        date_diff('day', SnapshotDate, AsOfDate)::BIGINT AS SnapshotFreshnessDays
    FROM snapshot_demand
)
SELECT
    SnapshotDate,
    DistributorID,
    ProductID,
    OnHandQty AS OnHandQuantity,
    InTransitQty AS InTransitQuantity,
    ReorderPoint,
    ExpiredQty AS ExpiredQuantity,
    AvailableInventoryQty,
    SnapshotFreshnessDays,
    CASE WHEN OnHandQty < ReorderPoint THEN 1 ELSE 0 END
        AS CurrentReorderException,
    Trailing3CompleteMonthsSalesQuantity,
    Prior3CompleteMonthsSalesQuantity,
    Trailing3CompleteMonthsSalesQuantity / NULLIF(TrailingWindowDays, 0)
        AS SalesVelocityQuantityPerDay,
    (Trailing3CompleteMonthsSalesQuantity - Prior3CompleteMonthsSalesQuantity)
        / NULLIF(Prior3CompleteMonthsSalesQuantity, 0) AS DemandTrendPct,
    AvailableInventoryQty
        / NULLIF(
            Trailing3CompleteMonthsSalesQuantity / NULLIF(TrailingWindowDays, 0),
            0
        ) AS InventoryCoverageDaysProxy
FROM derived;
