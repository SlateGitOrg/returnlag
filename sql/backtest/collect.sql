-- Append the as-of week's estimates for cohorts aged 0..backtest_max_age, one row per method.
INSERT INTO bt_estimates
SELECT getvariable('asof_week') AS as_of, ship_week, category, segment, age_weeks,
       'naive' AS method, observed_rate AS estimate
FROM fct_ultimates WHERE age_weeks BETWEEN 0 AND getvariable('backtest_max_age')
UNION ALL
SELECT getvariable('asof_week'), ship_week, category, segment, age_weeks,
       'chain_ladder', chain_ladder_rate
FROM fct_ultimates WHERE age_weeks BETWEEN 0 AND getvariable('backtest_max_age')
UNION ALL
SELECT getvariable('asof_week'), ship_week, category, segment, age_weeks,
       'bornhuetter_ferguson', bf_rate
FROM fct_ultimates WHERE age_weeks BETWEEN 0 AND getvariable('backtest_max_age')
UNION ALL
SELECT getvariable('asof_week'), ship_week, category, segment, age_weeks,
       'chain_ladder_pooled', chain_ladder_rate
FROM fct_ultimates_pooled WHERE age_weeks BETWEEN 0 AND getvariable('backtest_max_age');
