USE casework;

CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  table_name VARCHAR(64) NOT NULL,
  record_key VARCHAR(80) NOT NULL,
  action VARCHAR(10) NOT NULL,
  old_values JSON NULL,
  new_values JSON NULL,
  changed_by VARCHAR(80) NULL,
  changed_at VARCHAR(40) NOT NULL,
  INDEX idx_audit_record(table_name,record_key,id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS case_status_history (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  case_reference VARCHAR(80) NOT NULL,
  old_status VARCHAR(40) NULL,
  new_status VARCHAR(40) NULL,
  changed_by VARCHAR(80) NULL,
  changed_at VARCHAR(40) NOT NULL,
  INDEX idx_case_status_history_ref(case_reference,id)
) ENGINE=InnoDB;

DELIMITER $$
CREATE TRIGGER cases_audit_insert AFTER INSERT ON cases FOR EACH ROW
BEGIN
  INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at)
  VALUES('cases',NEW.case_ref,'INSERT',NULL,
    JSON_OBJECT('case_ref',NEW.case_ref,'title',NEW.title,'category',NEW.category,'status',NEW.status,'officer_id',NEW.officer_id,'opened_on',NEW.opened_on,'location',NEW.location),
    @app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'));
END$$
CREATE TRIGGER cases_audit_update AFTER UPDATE ON cases FOR EACH ROW
BEGIN
  INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at)
  VALUES('cases',NEW.case_ref,'UPDATE',
    JSON_OBJECT('case_ref',OLD.case_ref,'title',OLD.title,'category',OLD.category,'status',OLD.status,'officer_id',OLD.officer_id,'opened_on',OLD.opened_on,'location',OLD.location),
    JSON_OBJECT('case_ref',NEW.case_ref,'title',NEW.title,'category',NEW.category,'status',NEW.status,'officer_id',NEW.officer_id,'opened_on',NEW.opened_on,'location',NEW.location),
    @app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'));
END$$
CREATE TRIGGER cases_audit_delete AFTER DELETE ON cases FOR EACH ROW
BEGIN
  INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at)
  VALUES('cases',OLD.case_ref,'DELETE',
    JSON_OBJECT('case_ref',OLD.case_ref,'title',OLD.title,'category',OLD.category,'status',OLD.status,'officer_id',OLD.officer_id,'opened_on',OLD.opened_on,'location',OLD.location),
    NULL,@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'));
END$$
CREATE TRIGGER cases_status_history_update AFTER UPDATE ON cases FOR EACH ROW
BEGIN
  IF NOT (OLD.status <=> NEW.status) THEN
    INSERT INTO case_status_history(case_reference,old_status,new_status,changed_by,changed_at)
    VALUES(NEW.case_ref,OLD.status,NEW.status,@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'));
  END IF;
END$$
CREATE TRIGGER cases_block_closed_delete BEFORE DELETE ON cases FOR EACH ROW
BEGIN
  IF OLD.status='Closed' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CLOSED_CASE_DELETE: Closed cases cannot be deleted.';
  END IF;
END$$
CREATE TRIGGER cases_reject_reopen BEFORE UPDATE ON cases FOR EACH ROW
BEGIN
  IF OLD.status='Closed' AND NEW.status<>'Closed' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_INVALID_STATUS_TRANSITION: A closed case cannot be reopened or moved to another status.';
  END IF;
END$$
DELIMITER ;
