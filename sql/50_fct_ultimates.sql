-- One row per cohort at the as-of week: observed rate, chain-ladder ultimate and
-- Bornhuetter-Ferguson ultimate, all as a share of units shipped.
--   chain-ladder:  observed x CDF
--   BF:            observed + prior x (1 - 1/CDF)     (credibility = 1/CDF)
-- A cohort's latest observed cell is its development week min(age, max_dev). When no mature
-- cohort exists to give a prior (very early as-of weeks), BF falls back to chain-ladder.
CREATE OR REPLACE TABLE fct_ultimates AS
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
    INNER JOIN int_cdf AS c USING (category, segment, dev_week)
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
