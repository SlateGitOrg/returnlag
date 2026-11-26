-- Shipments dated on or before the as-of week, with ship week and season segment.
-- Week numbers are indices from week1_start; segment follows the ISO week of the ship date.
CREATE OR REPLACE TABLE stg_shipments AS
SELECT
    shipment_id,
    ship_date,
    (ship_date - getvariable('week1_start')) // 7 + 1 AS ship_week,
    category,
    CASE
        WHEN weekofyear(ship_date) BETWEEN getvariable('holiday_iso_first')
            AND getvariable('holiday_iso_last') THEN 'holiday'
        ELSE 'regular'
    END AS segment,
    units
FROM raw_shipments
WHERE (ship_date - getvariable('week1_start')) // 7 + 1 <= getvariable('asof_week');
