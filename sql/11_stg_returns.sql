-- Returns dated on or before the as-of week, joined to the shipment they belong to.
-- A return that cannot be matched to a shipment known by the as-of week, that is dated before
-- its shipment (scanner clock error) or that falls outside the development window is rejected
-- into dq_rejects with a reason; everything else becomes stg_returns.
CREATE OR REPLACE TEMP TABLE returns_checked AS
SELECT
    r.return_id,
    r.shipment_id,
    r.return_date,
    (r.return_date - getvariable('week1_start')) // 7 + 1 AS return_week,
    r.grade,
    s.ship_date,
    s.ship_week,
    s.category,
    s.segment,
    CASE
        WHEN s.shipment_id IS NULL THEN 'no_shipment_by_as_of'
        WHEN r.return_date < s.ship_date THEN 'returned_before_shipment'
        WHEN (r.return_date - getvariable('week1_start')) // 7 + 1 - s.ship_week
            > getvariable('max_dev') THEN 'beyond_development_window'
    END AS reason
FROM raw_returns AS r
LEFT JOIN stg_shipments AS s USING (shipment_id)
WHERE (r.return_date - getvariable('week1_start')) // 7 + 1 <= getvariable('asof_week');

CREATE OR REPLACE TABLE dq_rejects AS
SELECT return_id, shipment_id, return_date, ship_date, reason
FROM returns_checked
WHERE reason IS NOT NULL
ORDER BY return_id;

CREATE OR REPLACE TABLE stg_returns AS
SELECT
    return_id,
    shipment_id,
    category,
    segment,
    ship_date,
    ship_week,
    return_date,
    return_week,
    return_week - ship_week AS dev_week,
    grade
FROM returns_checked
WHERE reason IS NULL;

DROP TABLE returns_checked;
