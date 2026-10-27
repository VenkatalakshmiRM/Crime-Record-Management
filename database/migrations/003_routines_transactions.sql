USE casework;

SET @casework_resolution_ddl = IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cases' AND COLUMN_NAME='resolution')=0,
  'ALTER TABLE cases ADD COLUMN resolution TEXT NULL',
  'DO 0'
);
PREPARE casework_resolution_stmt FROM @casework_resolution_ddl;
EXECUTE casework_resolution_stmt;
DEALLOCATE PREPARE casework_resolution_stmt;

DROP TRIGGER IF EXISTS cases_audit_insert;
DROP TRIGGER IF EXISTS cases_audit_update;
DROP TRIGGER IF EXISTS cases_audit_delete;
DROP PROCEDURE IF EXISTS assign_officer;
DROP PROCEDURE IF EXISTS close_case;
DROP PROCEDURE IF EXISTS transfer_officer_cases;
DROP FUNCTION IF EXISTS days_open;

DELIMITER $$
CREATE TRIGGER cases_audit_insert AFTER INSERT ON cases FOR EACH ROW
BEGIN
  INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at)
  VALUES('cases',NEW.case_ref,'INSERT',NULL,
    JSON_OBJECT('case_ref',NEW.case_ref,'title',NEW.title,'category',NEW.category,'status',NEW.status,'officer_id',NEW.officer_id,'opened_on',NEW.opened_on,'location',NEW.location,'resolution',NEW.resolution),
    @app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'));
END$$
CREATE TRIGGER cases_audit_update AFTER UPDATE ON cases FOR EACH ROW
BEGIN
  INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at)
  VALUES('cases',NEW.case_ref,'UPDATE',
    JSON_OBJECT('case_ref',OLD.case_ref,'title',OLD.title,'category',OLD.category,'status',OLD.status,'officer_id',OLD.officer_id,'opened_on',OLD.opened_on,'location',OLD.location,'resolution',OLD.resolution),
    JSON_OBJECT('case_ref',NEW.case_ref,'title',NEW.title,'category',NEW.category,'status',NEW.status,'officer_id',NEW.officer_id,'opened_on',NEW.opened_on,'location',NEW.location,'resolution',NEW.resolution),
    @app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'));
END$$
CREATE TRIGGER cases_audit_delete AFTER DELETE ON cases FOR EACH ROW
BEGIN
  INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at)
  VALUES('cases',OLD.case_ref,'DELETE',
    JSON_OBJECT('case_ref',OLD.case_ref,'title',OLD.title,'category',OLD.category,'status',OLD.status,'officer_id',OLD.officer_id,'opened_on',OLD.opened_on,'location',OLD.location,'resolution',OLD.resolution),
    NULL,@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'));
END$$

CREATE PROCEDURE assign_officer(IN p_case_ref VARCHAR(80))
BEGIN
  DECLARE v_case_id BIGINT UNSIGNED DEFAULT NULL;
  DECLARE v_officer_id BIGINT UNSIGNED DEFAULT NULL;
  SELECT id INTO v_case_id FROM cases WHERE case_ref=p_case_ref;
  IF v_case_id IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CASE_NOT_FOUND: Case record was not found.'; END IF;
  IF (SELECT status FROM cases WHERE id=v_case_id)='Closed' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CASE_ALREADY_CLOSED: Closed cases cannot be reassigned.'; END IF;
  SELECT o.id INTO v_officer_id
  FROM officers o LEFT JOIN cases c ON c.officer_id=o.id AND c.status='Active'
  GROUP BY o.id ORDER BY COUNT(c.id),o.id LIMIT 1;
  IF v_officer_id IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_NO_OFFICERS: No team members are available for assignment.'; END IF;
  UPDATE cases SET officer_id=v_officer_id,updated_at=DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ') WHERE id=v_case_id;
END$$

CREATE PROCEDURE close_case(IN p_case_ref VARCHAR(80),IN p_resolution TEXT,IN p_user VARCHAR(80))
BEGIN
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SET @app_user=p_user;
  IF NOT EXISTS(SELECT 1 FROM cases WHERE case_ref=p_case_ref) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CASE_NOT_FOUND: Case record was not found.'; END IF;
  IF EXISTS(SELECT 1 FROM cases WHERE case_ref=p_case_ref AND status='Closed') THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CASE_ALREADY_CLOSED: Case is already closed.'; END IF;
  UPDATE cases SET status='Closed',resolution=p_resolution,updated_at=DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ') WHERE case_ref=p_case_ref;
  INSERT INTO activity(action,record_type,record_ref,description,actor,created_at)
  VALUES('closed','case',p_case_ref,CONCAT('Case closed: ',p_resolution),p_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'));
  COMMIT;
END$$

CREATE PROCEDURE transfer_officer_cases(IN p_from_badge VARCHAR(80),IN p_to_badge VARCHAR(80))
BEGIN
  DECLARE v_from_id BIGINT UNSIGNED DEFAULT NULL;
  DECLARE v_to_id BIGINT UNSIGNED DEFAULT NULL;
  DECLARE v_moved INT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT id INTO v_from_id FROM officers WHERE badge=p_from_badge;
  SELECT id INTO v_to_id FROM officers WHERE badge=p_to_badge;
  IF v_from_id IS NULL OR v_to_id IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_OFFICER_NOT_FOUND: Source or destination team member was not found.'; END IF;
  IF v_from_id=v_to_id THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_SAME_OFFICER: Choose a different destination team member.'; END IF;
  UPDATE cases SET officer_id=v_to_id,updated_at=DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ') WHERE officer_id=v_from_id;
  SET v_moved=ROW_COUNT();
  INSERT INTO activity(action,record_type,record_ref,description,actor,created_at)
  VALUES('transferred','officer',p_from_badge,CONCAT('Transferred ',v_moved,' case assignments to ',p_to_badge),@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'));
  COMMIT;
END$$

CREATE FUNCTION days_open(p_case_ref VARCHAR(80)) RETURNS INT
NOT DETERMINISTIC READS SQL DATA SQL SECURITY INVOKER
BEGIN
  DECLARE v_open DATE DEFAULT NULL;
  DECLARE v_end DATE DEFAULT NULL;
  DECLARE v_status VARCHAR(40) DEFAULT NULL;
  SELECT COALESCE(opened_on,STR_TO_DATE(SUBSTRING(created_at,1,10),'%Y-%m-%d')),status,CURDATE()
    INTO v_open,v_status,v_end FROM cases WHERE case_ref=p_case_ref;
  IF v_open IS NULL THEN RETURN 0; END IF;
  IF v_status='Closed' THEN
    SELECT STR_TO_DATE(SUBSTRING(changed_at,1,10),'%Y-%m-%d') INTO v_end FROM case_status_history
      WHERE case_reference=p_case_ref AND new_status='Closed' ORDER BY id DESC LIMIT 1;
    IF v_end IS NULL THEN SELECT STR_TO_DATE(SUBSTRING(updated_at,1,10),'%Y-%m-%d') INTO v_end FROM cases WHERE case_ref=p_case_ref; END IF;
  END IF;
  RETURN GREATEST(DATEDIFF(COALESCE(v_end,CURDATE()),v_open),0);
END$$
DELIMITER ;
