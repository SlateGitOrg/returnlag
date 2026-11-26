-- Bornhuetter-Ferguson prior: the volume-weighted final rate of the most recent prior_cohorts
-- fully developed cohorts (aged >= prior_min_age weeks) of the same category and segment.
-- A segment with no mature cohort falls back to the category's mature cohorts across segments.
CREATE OR REPLACE TABLE int_prior AS
WITH mature AS (
    SELECT category, segment, ship_week, units_shipped, cum_returned
    FROM int_triangle
    WHERE dev_week = getvariable('max_dev')
        AND getvariable('asof_week') - ship_week >= getvariable('prior_min_age')
),
by_segment AS (
    SELECT
        category,
        segment,
        count(*) AS n_cohorts,
        sum(cum_returned)::DOUBLE / sum(units_shipped) AS prior_rate
    FROM (
        SELECT *, row_number() OVER (
            PARTITION BY category, segment ORDER BY ship_week DESC
        ) AS rn
        FROM mature
    )
    WHERE rn <= getvariable('prior_cohorts')
    GROUP BY category, segment
),
by_category AS (
    SELECT
        category,
        count(*) AS n_cohorts,
        sum(cum_returned)::DOUBLE / sum(units_shipped) AS prior_rate
    FROM (
        SELECT *, row_number() OVER (PARTITION BY category ORDER BY ship_week DESC) AS rn
        FROM mature
    )
    WHERE rn <= getvariable('prior_cohorts')
    GROUP BY category
)
SELECT
    s.category,
    s.segment,
    coalesce(bs.prior_rate, bc.prior_rate) AS prior_rate,
    coalesce(bs.n_cohorts, bc.n_cohorts, 0) AS n_cohorts,
    CASE
        WHEN bs.prior_rate IS NOT NULL THEN 'segment'
        WHEN bc.prior_rate IS NOT NULL THEN 'category'
        ELSE 'none'
    END AS prior_source
FROM (SELECT DISTINCT category, segment FROM int_triangle) AS s
LEFT JOIN by_segment AS bs USING (category, segment)
LEFT JOIN by_category AS bc USING (category)
ORDER BY s.category, s.segment;
