-- Volume-weighted age-to-age factors per category x segment, from cells observable at the as-of
-- date: factor(d) = sum of cumulative returns at d+1 / sum at d over cohorts that have both.
-- Where nothing is observable the factor is 1.0. The tail factor after max_dev is 1.0.
CREATE OR REPLACE TABLE int_factors AS
WITH pairs AS (
    SELECT
        a.category,
        a.segment,
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
    SELECT g.category, g.segment, d.from_dev
    FROM (SELECT DISTINCT category, segment FROM int_triangle) AS g
    CROSS JOIN (SELECT unnest(range(0, getvariable('max_dev'))) AS from_dev) AS d
)
SELECT
    g.category,
    g.segment,
    g.from_dev,
    coalesce(p.n_cohorts, 0) AS n_cohorts,
    CASE WHEN p.cum_from > 0 THEN p.cum_to::DOUBLE / p.cum_from ELSE 1.0 END AS factor
FROM grid AS g
LEFT JOIN pairs AS p USING (category, segment, from_dev)
UNION ALL
SELECT category, segment, getvariable('max_dev') AS from_dev, 0 AS n_cohorts, 1.0 AS factor
FROM (SELECT DISTINCT category, segment FROM int_triangle)
ORDER BY category, segment, from_dev;
