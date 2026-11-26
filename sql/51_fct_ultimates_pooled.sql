-- The same ultimates computed from category-only (segment-pooled) factors, for comparison with
-- the segmented chain-ladder. The BF prior is the same segment-level prior.
CREATE OR REPLACE TABLE fct_ultimates_pooled AS
WITH latest AS (
    SELECT
        t.ship_week,
        t.category,
        t.segment,
        getvariable('asof_week') - t.ship_week AS age_weeks,
        t.dev_week,
        t.units_shipped,
        t.cum_returned AS observed_returns,
        t.cum_returned::DOUBLE / t.units_shipped AS observed_rate,
        c.cdf
    FROM int_triangle AS t
    INNER JOIN int_cdf_pooled AS c USING (category, dev_week)
    WHERE t.dev_week = least(getvariable('asof_week') - t.ship_week, getvariable('max_dev'))
)
SELECT
    l.ship_week,
    l.category,
    l.segment,
    l.age_weeks,
    l.dev_week,
    l.units_shipped,
    l.observed_returns,
    l.observed_rate,
    l.cdf,
    1.0 / l.cdf AS credibility,
    l.observed_rate * l.cdf AS chain_ladder_rate,
    p.prior_rate,
    CASE
        WHEN p.prior_rate IS NULL THEN l.observed_rate * l.cdf
        ELSE l.observed_rate + p.prior_rate * (1 - 1.0 / l.cdf)
    END AS bf_rate
FROM latest AS l
LEFT JOIN int_prior AS p USING (category, segment)
ORDER BY l.category, l.ship_week;
