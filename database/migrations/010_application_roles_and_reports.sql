-- CASEWORK role replacement and CID investigation reports.
-- Run once against an existing MySQL database, then restart the API.

ALTER TABLE users
  MODIFY role ENUM('Admin','NCO','CID','Administrator','Management Head','Operator') NOT NULL;

UPDATE users
SET role = CASE role
  WHEN 'Management Head' THEN 'Admin'
  WHEN 'Administrator' THEN 'NCO'
  WHEN 'Operator' THEN 'CID'
  ELSE role
END;

ALTER TABLE users
  MODIFY role ENUM('Admin','NCO','CID') NOT NULL;

ALTER TABLE users ADD COLUMN officer_id BIGINT UNSIGNED NULL;
ALTER TABLE users ADD CONSTRAINT fk_users_officer
  FOREIGN KEY(officer_id) REFERENCES officers(id) ON DELETE SET NULL;

-- Sessions issued under the old role matrix must authenticate again.
DELETE FROM sessions;

CREATE TABLE IF NOT EXISTS investigation_reports (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  case_reference VARCHAR(80) NOT NULL,
  officer_id BIGINT UNSIGNED NOT NULL,
  report_text TEXT NOT NULL,
  created_by VARCHAR(80) NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  INDEX idx_investigation_reports_case(case_reference,created_at),
  CONSTRAINT fk_investigation_reports_case FOREIGN KEY(case_reference) REFERENCES cases(case_ref) ON DELETE CASCADE,
  CONSTRAINT fk_investigation_reports_officer FOREIGN KEY(officer_id) REFERENCES officers(id) ON DELETE RESTRICT
) ENGINE=InnoDB;
