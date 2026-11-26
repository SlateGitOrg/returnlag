-- Every staged return sits in a development week 0..max_dev and inside the as-of week.
SELECT return_id, dev_week, return_week
FROM stg_returns
WHERE dev_week < 0
    OR dev_week > getvariable('max_dev')
    OR return_week > getvariable('asof_week');
