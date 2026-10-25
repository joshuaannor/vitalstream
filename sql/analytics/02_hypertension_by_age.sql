-- Q2: How does hypertension and blood pressure vary by age group?
-- Skills: GROUP BY on a derived column, conditional counts, averages, safe division.
SELECT
    age_group,
    count(*) AS patients,
    count(*) FILTER (WHERE has_hypertension) AS with_hypertension,
    round(100 * CAST(count(*) FILTER (WHERE has_hypertension) AS DOUBLE) / count(*), 1) AS pct_hypertension,
    round(avg(latest_systolic), 1) AS avg_latest_systolic,
    count(*) FILTER (WHERE latest_systolic >= 130) AS systolic_130_plus
FROM vitalstream_gold.patient_summary
WHERE NOT is_deceased
GROUP BY age_group
ORDER BY age_group
