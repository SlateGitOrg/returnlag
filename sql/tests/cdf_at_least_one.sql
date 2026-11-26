-- Cumulative development factors are >= 1 (segmented and pooled).
SELECT category, segment, dev_week, cdf FROM int_cdf WHERE cdf < 1 - 1e-9
UNION ALL
SELECT category, NULL AS segment, dev_week, cdf FROM int_cdf_pooled WHERE cdf < 1 - 1e-9;
