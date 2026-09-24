-- Act 1: the naive raw answer ("confidently wrong").
-- Valid SQL, valid arithmetic, wrong data contract:
--   * reads raw landing rows directly, so the replayed duplicate order is counted twice
--   * calls SUM(gross_amount) "revenue" and treats USD amounts as if they were CAD
--   * ignores returns entirely
--   * checks no freshness, no quality gate and no approved metric definition
SELECT
    o.category_code,
    c.category_name,
    COUNT(*) AS order_rows,
    SUM(CASE WHEN o.currency_code <> 'CAD' THEN 1 ELSE 0 END) AS non_cad_rows,
    SUM(o.gross_amount) AS revenue,
    t.target_cad,
    MAX(o.ingested_at) AS latest_ingested_at
FROM bronze_orders AS o
JOIN ref_categories AS c
    ON c.category_code = o.category_code
JOIN bronze_targets AS t
    ON t.region_code = o.region_code
   AND t.category_code = o.category_code
   AND t.target_month = '2026-08'
WHERE o.region_code = 'ON'
  AND o.order_timestamp_utc >= '2026-08-01'
  AND o.order_timestamp_utc < '2026-09-01'
GROUP BY o.category_code, c.category_name, t.target_cad
ORDER BY o.category_code;
