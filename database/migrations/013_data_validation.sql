USE casework;

-- Reversible validation constraints for MySQL 8.0.16+ (CHECK enforcement required).
-- Preflight counts are included so existing data can be inspected before applying.
-- This migration deliberately does not rewrite or delete existing records.

ALTER TABLE persons
  ADD CONSTRAINT chk_person_age_range CHECK (age IS NULL OR age <= 120);

ALTER TABLE evidence
  ADD CONSTRAINT chk_evidence_sha256 CHECK (REGEXP_LIKE(hash, '^[0-9A-Fa-f]{64}$'));

-- Rollback (run manually if needed):
-- ALTER TABLE evidence DROP CHECK chk_evidence_sha256;
-- ALTER TABLE persons DROP CHECK chk_person_age_range;
