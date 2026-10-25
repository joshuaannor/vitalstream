-- How common each disorder is: patients ever and currently affected, % of all patients, and rank.
-- partitioned_by: none
-- Skills: COUNT(DISTINCT), CROSS JOIN to a total, safe division, DENSE_RANK().
WITH population AS (
    SELECT count(*) AS total_patients
    FROM vitalstream_silver.patients
),

per_condition AS (
    SELECT
        code,
        max(code_display) AS condition,
        count(DISTINCT patient_id) AS patients_ever,
        count(DISTINCT patient_id) FILTER (WHERE clinical_status = 'active') AS patients_active
    FROM vitalstream_silver.conditions
    WHERE semantic_tag = 'disorder'   -- skip findings like "Full-time employment"
    GROUP BY code
)

SELECT
    c.code,
    c.condition,
    c.patients_ever,
    c.patients_active,
    -- CAST to DOUBLE: in Athena, integer / integer drops the decimals
    round(100 * CAST(c.patients_ever AS DOUBLE) / p.total_patients, 1) AS pct_ever,
    round(100 * CAST(c.patients_active AS DOUBLE) / p.total_patients, 1) AS pct_active,
    dense_rank() OVER (ORDER BY c.patients_ever DESC) AS rank_ever,
    dense_rank() OVER (ORDER BY c.patients_active DESC) AS rank_active
FROM per_condition c
CROSS JOIN population p
