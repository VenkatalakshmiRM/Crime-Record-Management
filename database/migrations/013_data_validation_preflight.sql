USE casework;

-- Review these results before applying 013_data_validation.sql.
SELECT COUNT(*) AS invalid_person_ages FROM persons WHERE age IS NOT NULL AND age > 120;
SELECT COUNT(*) AS invalid_evidence_hashes FROM evidence WHERE NOT REGEXP_LIKE(hash, '^[0-9A-Fa-f]{64}$');
SELECT COUNT(*) AS malformed_case_dates FROM cases WHERE opened_on IS NULL;
