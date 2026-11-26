-- Score every estimate against the developed rate of the same cohort (all development weeks
-- observed in the final build). Errors are in percentage points.
CREATE OR REPLACE TABLE backtest_scores AS
SELECT
    e.as_of,
    e.ship_week,
    e.category,
    e.segment,
    e.age_weeks,
    CASE
        WHEN e.age_weeks <= 1 THEN '0-1'
        WHEN e.age_weeks <= 4 THEN '2-4'
        ELSE '5-8'
    END AS age_band,
    e.method,
    e.estimate,
    a.actual_rate,
    abs(e.estimate - a.actual_rate) * 100 AS abs_error_pp,
    (e.estimate - a.actual_rate) * 100 AS error_pp
FROM bt_estimates AS e
INNER JOIN bt_actuals AS a USING (ship_week, category)
ORDER BY e.as_of, e.category, e.ship_week, e.method;
