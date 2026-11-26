-- Cumulative returned units never fall as development weeks advance.
SELECT a.category, a.ship_week, a.dev_week, a.cum_returned, b.cum_returned AS next_cum_returned
FROM int_triangle AS a
INNER JOIN int_triangle AS b
    ON a.category = b.category AND a.ship_week = b.ship_week AND b.dev_week = a.dev_week + 1
WHERE b.cum_returned < a.cum_returned;
