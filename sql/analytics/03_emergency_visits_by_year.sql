-- Q3: Are emergency visits going up or down year over year?
-- Skills: aggregating a gold table further, LAG() for year-over-year change.
WITH yearly AS (
    SELECT
        extract(year FROM month) AS year,
        CAST(sum(encounters) AS BIGINT) AS emergency_visits
    FROM vitalstream_gold.encounters_monthly
    WHERE class_code = 'EMER'
    GROUP BY extract(year FROM month)
)
SELECT
    year,
    emergency_visits,
    emergency_visits - lag(emergency_visits) OVER (ORDER BY year) AS change_vs_prev_year
FROM yearly
ORDER BY year
