-- No return dated before its shipment survives staging.
SELECT return_id, shipment_id, ship_date, return_date
FROM stg_returns
WHERE return_date < ship_date;
