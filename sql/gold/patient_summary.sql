-- One row per patient: demographics, visits, chronic conditions and latest vitals.
-- partitioned_by: none
-- Skills: CTEs, LEFT JOINs, GROUP BY with FILTER, ROW_NUMBER() to pick the latest reading.
WITH snapshot AS (
    -- "Today" for this dataset = the latest visit date, so results don't drift with the calendar
    SELECT max(CAST(start_at AS DATE)) AS as_of
    FROM vitalstream_silver.encounters
),

people AS (
    SELECT
        p.patient_id,
        p.gender,
        p.race,
        p.ethnicity,
        p.birth_date,
        p.deceased_at,
        coalesce(CAST(p.deceased_at AS DATE), s.as_of) AS age_date
    FROM vitalstream_silver.patients p
    CROSS JOIN snapshot s
),

visits AS (
    SELECT
        patient_id,
        count(*) AS encounter_count,
        count(*) FILTER (WHERE class_code = 'EMER') AS emergency_visits,
        count(*) FILTER (WHERE class_code = 'IMP') AS inpatient_stays,
        min(start_at) AS first_encounter_at,
        max(start_at) AS last_encounter_at
    FROM vitalstream_silver.encounters
    GROUP BY patient_id
),

diagnoses AS (
    SELECT
        patient_id,
        count(DISTINCT code) FILTER (WHERE clinical_status = 'active' AND semantic_tag = 'disorder')
            AS active_disorders,
        bool_or(code = '44054006') AS has_diabetes,       -- Diabetes mellitus type 2
        bool_or(code = '714628002') AS has_prediabetes,   -- Prediabetes
        bool_or(code = '59621000') AS has_hypertension    -- Essential hypertension
    FROM vitalstream_silver.conditions
    GROUP BY patient_id
),

latest_vitals AS (
    -- Rank each patient's readings of each vital, newest first, and keep rank 1
    SELECT
        patient_id,
        max(value_num) FILTER (WHERE code = '8480-6') AS latest_systolic,
        max(value_num) FILTER (WHERE code = '8462-4') AS latest_diastolic,
        max(value_num) FILTER (WHERE code = '39156-5') AS latest_bmi
    FROM (
        SELECT
            patient_id,
            code,
            value_num,
            row_number() OVER (PARTITION BY patient_id, code ORDER BY effective_at DESC) AS rn
        FROM vitalstream_silver.observations
        WHERE code IN ('8480-6', '8462-4', '39156-5')
    ) ranked
    WHERE rn = 1
    GROUP BY patient_id
),

aged AS (
    -- Whole years between birth and age_date (subtract 1 if the birthday hasn't come yet)
    SELECT
        *,
        extract(year FROM age_date) - extract(year FROM birth_date)
            - CASE WHEN extract(month FROM age_date) * 100 + extract(day FROM age_date)
                      < extract(month FROM birth_date) * 100 + extract(day FROM birth_date)
                   THEN 1 ELSE 0 END AS age_years
    FROM people
)

SELECT
    a.patient_id,
    a.gender,
    a.race,
    a.ethnicity,
    a.birth_date,
    a.age_years,
    CASE
        WHEN a.age_years < 18 THEN '0-17'
        WHEN a.age_years < 40 THEN '18-39'
        WHEN a.age_years < 65 THEN '40-64'
        ELSE '65+'
    END AS age_group,
    a.deceased_at IS NOT NULL AS is_deceased,
    coalesce(v.encounter_count, 0) AS encounter_count,
    coalesce(v.emergency_visits, 0) AS emergency_visits,
    coalesce(v.inpatient_stays, 0) AS inpatient_stays,
    v.first_encounter_at,
    v.last_encounter_at,
    coalesce(d.active_disorders, 0) AS active_disorders,
    coalesce(d.has_diabetes, false) AS has_diabetes,
    coalesce(d.has_prediabetes, false) AS has_prediabetes,
    coalesce(d.has_hypertension, false) AS has_hypertension,
    lv.latest_systolic,
    lv.latest_diastolic,
    lv.latest_bmi
FROM aged a
LEFT JOIN visits v ON v.patient_id = a.patient_id
LEFT JOIN diagnoses d ON d.patient_id = a.patient_id
LEFT JOIN latest_vitals lv ON lv.patient_id = a.patient_id
