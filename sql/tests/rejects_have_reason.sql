-- Every rejected return carries a reason, and rejected ids are absent from stg_returns.
SELECT d.return_id, d.reason
FROM dq_rejects AS d
LEFT JOIN stg_returns AS s USING (return_id)
WHERE d.reason IS NULL OR s.return_id IS NOT NULL;
