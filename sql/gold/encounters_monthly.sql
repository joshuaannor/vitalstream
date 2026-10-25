-- Visits per month and visit class, with change vs the previous month and a year-to-date total.
-- partitioned_by: none
-- Skills: date_trunc, GROUP BY, LAG() and running SUM() window functions.
WITH snapshot AS (
    SELECT max(start_at) AS as_of
    FROM vitalstream_silver.encounters
),

monthly AS (
    SELECT
        CAST(date_trunc('month', e.start_at) AS DATE) AS month,
        e.class_code,
        count(*) AS encounters,
        count(DISTINCT e.patient_id) AS patients,
        round(avg(CAST(date_diff('second', e.start_at, e.end_at) AS DOUBLE)) / 60, 1) AS avg_duration_min
    FROM vitalstream_silver.encounters e
    CROSS JOIN snapshot s
    -- Last 10 years; older visits are sparse carry-overs from long-running conditions
    WHERE e.start_at >= s.as_of - INTERVAL '10' YEAR
    GROUP BY CAST(date_trunc('month', e.start_at) AS DATE), e.class_code
)

SELECT
    month,
    class_code,
    encounters,
    patients,
    avg_duration_min,
    -- Compared with the previous month that had visits of this class
    encounters - lag(encounters) OVER (PARTITION BY class_code ORDER BY month) AS change_vs_prev_month,
    CAST(sum(encounters) OVER (
        PARTITION BY class_code, extract(year FROM month)
        ORDER BY month
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS BIGINT) AS ytd_encounters
FROM monthly
