-- No ultimate rate falls below what has already been observed.
SELECT 'segmented' AS variant, category, ship_week, observed_rate, chain_ladder_rate, bf_rate
FROM fct_ultimates
WHERE chain_ladder_rate < observed_rate - 1e-9 OR bf_rate < observed_rate - 1e-9
UNION ALL
SELECT 'pooled' AS variant, category, ship_week, observed_rate, chain_ladder_rate, bf_rate
FROM fct_ultimates_pooled
WHERE chain_ladder_rate < observed_rate - 1e-9 OR bf_rate < observed_rate - 1e-9;
