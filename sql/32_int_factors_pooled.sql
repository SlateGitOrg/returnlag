-- The same factors and cumulative factors with the season segment pooled away (category only).
-- Used as the comparison for the segmented chain-ladder.
CREATE OR REPLACE TABLE int_factors_pooled AS
WITH pairs AS (
    SELECT
        a.category,
        a.dev_week AS from_dev,
        count(*) AS n_cohorts,
        sum(a.cum_returned) AS cum_from,
        sum(b.cum_returned) AS cum_to
    FROM int_triangle AS a
    INNER JOIN int_triangle AS b
        ON a.category = b.category
        AND a.ship_week = b.ship_week
        AND b.dev_week = a.dev_week + 1
    GROUP BY ALL
),
grid AS (
    SELECT g.category, d.from_dev
    FROM (SELECT DISTINCT category FROM int_triangle) AS g
    CROSS JOIN (SELECT unnest(range(0, getvariable('max_dev'))) AS from_dev) AS d
)
SELECT
    g.category,
    g.from_dev,
    coalesce(p.n_cohorts, 0) AS n_cohorts,
    CASE WHEN p.cum_from > 0 THEN p.cum_to::DOUBLE / p.cum_from ELSE 1.0 END AS factor
FROM grid AS g
LEFT JOIN pairs AS p USING (category, from_dev)
UNION ALL
SELECT category, getvariable('max_dev') AS from_dev, 0 AS n_cohorts, 1.0 AS factor
FROM (SELECT DISTINCT category FROM int_triangle)
ORDER BY category, from_dev;

CREATE OR REPLACE TABLE int_cdf_pooled AS
SELECT
    category,
    from_dev AS dev_week,
    exp(sum(ln(factor)) OVER (
        PARTITION BY category
        ORDER BY from_dev
        ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING
    )) AS cdf
FROM int_factors_pooled
ORDER BY category, dev_week;
