USE casework;

CREATE TABLE IF NOT EXISTS evidence (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  case_reference VARCHAR(80) NOT NULL,
  description TEXT NOT NULL,
  `type` VARCHAR(80) NOT NULL,
  hash CHAR(64) NOT NULL,
  storage_path VARCHAR(500) NOT NULL,
  collected_by BIGINT UNSIGNED NOT NULL,
  collected_at VARCHAR(40) NOT NULL,
  INDEX idx_evidence_case(case_reference,id),
  INDEX idx_evidence_collector(collected_by),
  CONSTRAINT fk_evidence_case FOREIGN KEY(case_reference) REFERENCES cases(case_ref) ON DELETE RESTRICT,
  CONSTRAINT fk_evidence_collector FOREIGN KEY(collected_by) REFERENCES officers(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS custody_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  evidence_id BIGINT UNSIGNED NOT NULL,
  from_officer BIGINT UNSIGNED NULL,
  to_officer BIGINT UNSIGNED NOT NULL,
  purpose VARCHAR(500) NOT NULL,
  transferred_at VARCHAR(40) NOT NULL,
  INDEX idx_custody_evidence(evidence_id,id),
  INDEX idx_custody_from_officer(from_officer),
  INDEX idx_custody_to_officer(to_officer),
  CONSTRAINT fk_custody_evidence FOREIGN KEY(evidence_id) REFERENCES evidence(id) ON DELETE RESTRICT,
  CONSTRAINT fk_custody_from_officer FOREIGN KEY(from_officer) REFERENCES officers(id) ON DELETE RESTRICT,
  CONSTRAINT fk_custody_to_officer FOREIGN KEY(to_officer) REFERENCES officers(id) ON DELETE RESTRICT
) ENGINE=InnoDB;

DROP TRIGGER IF EXISTS custody_log_no_update;
DROP TRIGGER IF EXISTS custody_log_no_delete;
DELIMITER $$
CREATE TRIGGER custody_log_no_update BEFORE UPDATE ON custody_log FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CUSTODY_APPEND_ONLY: Custody history cannot be updated.';
END$$
CREATE TRIGGER custody_log_no_delete BEFORE DELETE ON custody_log FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CUSTODY_APPEND_ONLY: Custody history cannot be deleted.';
END$$
DELIMITER ;
