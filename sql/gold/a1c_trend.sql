-- Every HbA1c result with the previous result, change, 3-test rolling average and clinical band.
-- partitioned_by: result_year
-- Skills: ROW_NUMBER(), LAG(), moving AVG() over a window frame, partitioning by event date.
-- Bands (ADA): normal < 5.7%, prediabetes 5.7-6.4%, diabetes >= 6.5%.
SELECT
    patient_id,
    observation_id,
    effective_at,
    value_num AS a1c_pct,
    row_number() OVER (PARTITION BY patient_id ORDER BY effective_at) AS test_number,
    lag(value_num) OVER (PARTITION BY patient_id ORDER BY effective_at) AS previous_a1c_pct,
    round(value_num - lag(value_num) OVER (PARTITION BY patient_id ORDER BY effective_at), 2)
        AS change_pct_points,
    round(avg(value_num) OVER (
        PARTITION BY patient_id
        ORDER BY effective_at
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ), 2) AS rolling_avg_3,
    CASE
        WHEN value_num >= 6.5 THEN 'diabetes'
        WHEN value_num >= 5.7 THEN 'prediabetes'
        ELSE 'normal'
    END AS a1c_band,
    CAST(extract(year FROM effective_at) AS INTEGER) AS result_year   -- partition column: must be last
FROM vitalstream_silver.observations
WHERE code = '4548-4'   -- LOINC: Hemoglobin A1c
