-- Q1: Which patients' HbA1c went up between their first and latest test, and did their band change?
-- Skills: JOIN two gold tables, GROUP BY + HAVING, min_by/max_by (value at earliest/latest time).
SELECT
    a.patient_id,
    s.gender,
    s.age_years,
    count(*) AS tests,
    min_by(a.a1c_pct, a.effective_at) AS first_a1c,
    max_by(a.a1c_pct, a.effective_at) AS latest_a1c,
    min_by(a.a1c_band, a.effective_at) AS first_band,
    max_by(a.a1c_band, a.effective_at) AS latest_band,
    s.has_prediabetes,
    s.has_diabetes
FROM vitalstream_gold.a1c_trend a
JOIN vitalstream_gold.patient_summary s ON s.patient_id = a.patient_id
GROUP BY a.patient_id, s.gender, s.age_years, s.has_prediabetes, s.has_diabetes
HAVING max_by(a.a1c_pct, a.effective_at) > min_by(a.a1c_pct, a.effective_at)
ORDER BY latest_a1c DESC
LIMIT 10
