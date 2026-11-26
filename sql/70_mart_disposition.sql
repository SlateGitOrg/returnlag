-- Disposition of returned units. Each returned unit is graded on receipt:
--   A restock (resold at full price), B outlet, C liquidate.
-- Recovery is a share of the unit's selling price; every return also costs handling.
-- Net return cost = refund - recovered value + handling.
-- ref_grade and ref_category_economics are assumptions loaded from config before the models run.
CREATE OR REPLACE TABLE mart_disposition AS
SELECT
    r.category,
    r.grade,
    g.disposition,
    count(*) AS returns,
    count(*)::DOUBLE / sum(count(*)) OVER (PARTITION BY r.category) AS share_of_category,
    g.recovery_pct,
    sum(e.unit_price) AS refunded_value,
    sum(e.unit_price * g.recovery_pct) AS recovered_value,
    sum(e.handling_cost) AS handling_cost,
    sum(e.unit_price * (1 - g.recovery_pct) + e.handling_cost) AS net_cost
FROM stg_returns AS r
INNER JOIN ref_grade AS g USING (grade)
INNER JOIN ref_category_economics AS e USING (category)
GROUP BY r.category, r.grade, g.disposition, g.recovery_pct
ORDER BY r.category, r.grade;

CREATE OR REPLACE TABLE mart_net_return_cost AS
SELECT
    category,
    sum(returns) AS returns,
    sum(refunded_value) AS refunded_value,
    sum(recovered_value) AS recovered_value,
    sum(net_cost) AS net_cost,
    sum(net_cost) / sum(returns) AS net_cost_per_return,
    sum(recovered_value) / sum(refunded_value) AS recovery_pct
FROM mart_disposition
GROUP BY category
ORDER BY category;
