-- Cumulative development factor at development week d: the product of the age-to-age factors
-- from d onwards, written as exp(sum(ln f)) over a window. pct_developed = 1 / cdf.
CREATE OR REPLACE TABLE int_cdf AS
WITH windowed AS (
    SELECT
        category,
        segment,
        from_dev AS dev_week,
        exp(sum(ln(factor)) OVER (
            PARTITION BY category, segment
            ORDER BY from_dev
            ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING
        )) AS cdf
    FROM int_factors
)
SELECT category, segment, dev_week, cdf, 1.0 / cdf AS pct_developed
FROM windowed
ORDER BY category, segment, dev_week;
