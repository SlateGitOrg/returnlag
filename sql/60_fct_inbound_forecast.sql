-- Expected returns arriving in each future week from cohorts already shipped:
--   (ultimate - observed) units, spread over the weeks still to come by the incremental
--   development pattern g(d) - g(d-1), g = 1/CDF, rescaled by the share not yet developed.
-- Calendar week of arrival = ship_week + development week. One row per method, week, category.
CREATE OR REPLACE TABLE fct_inbound_forecast AS
WITH ultimates AS (
    SELECT 'chain_ladder' AS method, *, chain_ladder_rate AS ultimate_rate FROM fct_ultimates
    UNION ALL
    SELECT 'bornhuetter_ferguson' AS method, *, bf_rate AS ultimate_rate FROM fct_ultimates
),
cohort_weeks AS (
    SELECT
        u.method,
        u.category,
        u.ship_week,
        u.ship_week + f.dev_week AS forecast_week,
        (u.ultimate_rate - u.observed_rate) * u.units_shipped
            * (f.pct_developed - prev.pct_developed) / (1 - u.credibility) AS expected_returns
    FROM ultimates AS u
    INNER JOIN int_cdf AS f
        ON f.category = u.category AND f.segment = u.segment AND f.dev_week > u.dev_week
    INNER JOIN int_cdf AS prev
        ON prev.category = u.category AND prev.segment = u.segment
        AND prev.dev_week = f.dev_week - 1
    WHERE u.credibility < 1
)
SELECT
    method,
    forecast_week,
    forecast_week - getvariable('asof_week') AS weeks_ahead,
    category,
    sum(expected_returns) AS expected_returns
FROM cohort_weeks
GROUP BY ALL
ORDER BY method, forecast_week, category;
