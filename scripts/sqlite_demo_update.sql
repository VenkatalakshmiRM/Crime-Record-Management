-- Run after sqlite_demo_insert.sql.
UPDATE cases
SET title = 'SQL demonstration: Riverside bicycle theft (updated)', status = 'Active', location = 'Riverside East', updated_at = datetime('now')
WHERE case_ref = 'CASE-2026-020';
