USE casework;

-- Rollback for 013_data_validation.sql.
ALTER TABLE evidence DROP CHECK chk_evidence_sha256;
ALTER TABLE persons DROP CHECK chk_person_age_range;
