-- Backfill legacy rows before making the core case details mandatory.
UPDATE cases
SET opened_on = COALESCE(opened_on, STR_TO_DATE(SUBSTRING(created_at, 1, 10), '%Y-%m-%d')),
    location = CASE WHEN TRIM(location) = '' THEN 'Not recorded' ELSE location END;

ALTER TABLE cases
  MODIFY opened_on DATE NOT NULL,
  MODIFY location VARCHAR(240) NOT NULL;
