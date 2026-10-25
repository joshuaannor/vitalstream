-- Q4: Do diagnoses agree with lab results? Diagnosis on record vs band of the latest HbA1c.
-- Skills: ROW_NUMBER() to pick the latest test, CASE to label groups, cross-tab with FILTER.
WITH latest_test AS (
    SELECT patient_id, a1c_band
    FROM (
        SELECT
            patient_id,
            a1c_band,
            row_number() OVER (PARTITION BY patient_id ORDER BY effective_at DESC) AS rn
        FROM vitalstream_gold.a1c_trend
    ) ranked
    WHERE rn = 1
)
SELECT
    CASE
        WHEN s.has_diabetes THEN 'diabetes'
        WHEN s.has_prediabetes THEN 'prediabetes'
        ELSE 'none'
    END AS diagnosis_on_record,
    count(*) AS patients_tested,
    count(*) FILTER (WHERE t.a1c_band = 'normal') AS latest_normal,
    count(*) FILTER (WHERE t.a1c_band = 'prediabetes') AS latest_prediabetes,
    count(*) FILTER (WHERE t.a1c_band = 'diabetes') AS latest_diabetes
FROM latest_test t
JOIN vitalstream_gold.patient_summary s ON s.patient_id = t.patient_id
GROUP BY 1
ORDER BY 1
