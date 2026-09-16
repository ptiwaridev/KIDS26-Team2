export const demoResult = {
  value: "4,218",
  label: "unique ICU patients",
  summary: "Of the qualifying ICU population, 4,218 patients were over 65 at the time of admission. This represents 26.8% of the selected cohort.",
  facts: [
    ["Population", "Adult ICU patients"],
    ["Age filter", "Over 65 years"],
    ["Counting", "Unique patients"],
  ],
  rows: [
    ["66–75", "2,486", "15.8%"],
    ["76–89", "1,421", "9.0%"],
    ["Over 89", "311", "2.0%"],
  ],
  sql: `SELECT
  CASE
    WHEN age BETWEEN 66 AND 75 THEN '66–75'
    WHEN age BETWEEN 76 AND 89 THEN '76–89'
    ELSE 'Over 89'
  END AS age_group,
  COUNT(DISTINCT subject_id) AS patients
FROM mimiciv_derived.age
JOIN mimiciv_icu.icustays USING (subject_id)
WHERE age > 65
GROUP BY age_group;`,
};
