-- Forecast arrivals are non-negative, fall in future weeks and only within the pattern horizon.
SELECT method, forecast_week, weeks_ahead, category, expected_returns
FROM fct_inbound_forecast
WHERE expected_returns < -1e-9
    OR weeks_ahead < 1
    OR weeks_ahead > getvariable('max_dev');
