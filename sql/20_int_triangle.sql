-- Development triangle. Cohort = ship week x category (the season segment follows from the week).
-- A cell (cohort, development week d) is observable when ship_week + d <= as-of week; only
-- observable cells exist, so nothing is extrapolated here.
CREATE OR REPLACE TABLE int_triangle AS
WITH cohorts AS (
    SELECT ship_week, category, segment, sum(units) AS units_shipped
    FROM stg_shipments
    GROUP BY ALL
),
cells AS (
    SELECT c.ship_week, c.category, c.segment, c.units_shipped, d.dev_week
    FROM cohorts AS c
    CROSS JOIN (SELECT unnest(range(0, getvariable('max_dev') + 1)) AS dev_week) AS d
    WHERE c.ship_week + d.dev_week <= getvariable('asof_week')
),
incremental AS (
    SELECT ship_week, category, dev_week, count(*) AS returned_units
    FROM stg_returns
    GROUP BY ALL
)
SELECT
    c.ship_week,
    c.category,
    c.segment,
    c.dev_week,
    c.units_shipped,
    sum(coalesce(i.returned_units, 0)) OVER (
        PARTITION BY c.ship_week, c.category
        ORDER BY c.dev_week
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS cum_returned
FROM cells AS c
LEFT JOIN incremental AS i USING (ship_week, category, dev_week)
ORDER BY c.category, c.ship_week, c.dev_week;
