CREATE DATABASE IF NOT EXISTS casework CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE casework;

CREATE TABLE IF NOT EXISTS users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(80) NOT NULL UNIQUE,
  password_hash VARCHAR(200) NOT NULL,
  name VARCHAR(160) NOT NULL,
  role ENUM('Administrator','Management Head','Operator') NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at VARCHAR(40) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS officers (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(160) NOT NULL,
  role VARCHAR(120) NOT NULL,
  badge VARCHAR(80) NOT NULL UNIQUE,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  INDEX idx_officers_role(role)
) ENGINE=InnoDB;


CREATE TABLE IF NOT EXISTS cases (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  case_ref VARCHAR(80) NOT NULL UNIQUE,
  title VARCHAR(240) NOT NULL,
  category VARCHAR(100) NOT NULL,
  status ENUM('Active','Under review','Pending','Closed') NOT NULL,
  officer_id BIGINT UNSIGNED NULL,
  opened_on DATE NULL,
  location VARCHAR(240) NOT NULL DEFAULT '',
  resolution TEXT NULL,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  INDEX idx_cases_status(status),
  INDEX idx_cases_status_category_opened(status,category,opened_on),
  INDEX idx_cases_category(category),
  INDEX idx_cases_location(location),
  INDEX idx_cases_officer(officer_id),
  INDEX idx_cases_opened(opened_on),
  CONSTRAINT fk_cases_officer FOREIGN KEY(officer_id) REFERENCES officers(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS persons (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(160) NOT NULL,
  case_id BIGINT UNSIGNED NULL,
  age SMALLINT UNSIGNED NULL,
  status ENUM('Under investigation','In custody','Released on bail','Wanted','Unknown') NOT NULL,
  charge VARCHAR(240) NOT NULL,
  created_at VARCHAR(40) NOT NULL,
  updated_at VARCHAR(40) NOT NULL,
  INDEX idx_persons_case(case_id),
  INDEX idx_persons_name(name),
  INDEX idx_persons_status(status),
  CONSTRAINT fk_persons_case FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS case_persons (
  case_reference VARCHAR(80) NOT NULL,
  person_id BIGINT UNSIGNED NOT NULL,
  role ENUM('suspect','witness','victim','person_of_interest') NOT NULL,
  added_at VARCHAR(40) NOT NULL,
  PRIMARY KEY (case_reference, person_id, role),
  INDEX idx_case_persons_person(person_id,case_reference),
  CONSTRAINT fk_case_persons_case FOREIGN KEY(case_reference) REFERENCES cases(case_ref) ON DELETE CASCADE,
  CONSTRAINT fk_case_persons_person FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE
) ENGINE=InnoDB;

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

CREATE TABLE IF NOT EXISTS hearings (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  case_reference VARCHAR(80) NOT NULL,
  court VARCHAR(240) NOT NULL,
  hearing_date DATE NOT NULL,
  status ENUM('Scheduled','Completed','Adjourned','Cancelled') NOT NULL,
  outcome TEXT NULL,
  notes TEXT NULL,
  INDEX idx_hearings_case(case_reference,hearing_date),
  INDEX idx_hearings_date_status(hearing_date,status),
  CONSTRAINT fk_hearings_case FOREIGN KEY(case_reference) REFERENCES cases(case_ref) ON DELETE RESTRICT
) ENGINE=InnoDB;



CREATE TABLE IF NOT EXISTS activity (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  action VARCHAR(60) NOT NULL,
  record_type VARCHAR(60) NOT NULL,
  record_ref VARCHAR(100) NOT NULL,
  description VARCHAR(300) NOT NULL,
  actor VARCHAR(80) NULL,
  created_at VARCHAR(40) NOT NULL,
  INDEX idx_activity_created(created_at),
  INDEX idx_activity_record(record_type,record_ref)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sessions (
  token_hash CHAR(64) PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  expires_at VARCHAR(40) NOT NULL,
  last_seen_at VARCHAR(40) NOT NULL,
  INDEX idx_sessions_expiry(expires_at),
  INDEX idx_sessions_user_id(user_id),
  CONSTRAINT fk_sessions_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS login_attempts (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  username_key CHAR(64) NOT NULL,
  ip_key CHAR(64) NOT NULL,
  attempted_at VARCHAR(40) NOT NULL,
  succeeded BOOLEAN NOT NULL DEFAULT FALSE,
  locked_until VARCHAR(40) NULL,
  INDEX idx_login_attempts_username_time(username_key,attempted_at),
  INDEX idx_login_attempts_ip_time(ip_key,attempted_at)
) ENGINE=InnoDB;

CREATE OR REPLACE VIEW case_view AS
SELECT c.id,c.case_ref,c.title,c.category,c.status,c.officer_id,o.name AS officer_name,
       c.opened_on,c.location,c.resolution,c.created_at,c.updated_at
FROM cases c LEFT JOIN officers o ON o.id=c.officer_id;

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

DELIMITER $$
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


-- Reporting views are available immediately after a fresh schema install.
CREATE OR REPLACE VIEW case_view AS
SELECT c.id,c.case_ref,c.title,c.category,c.status,c.officer_id,o.name AS officer_name,
       c.opened_on,c.location,c.resolution,c.created_at,c.updated_at
FROM cases c LEFT JOIN officers o ON o.id=c.officer_id;

CREATE OR REPLACE VIEW officer_workload_view AS
SELECT o.id AS officer_id,o.name AS officer_name,o.role,o.badge,
       COUNT(c.id) AS total_cases,
       COALESCE(SUM(CASE WHEN c.status='Closed' THEN 1 ELSE 0 END),0) AS closed_cases,
       COALESCE(SUM(CASE WHEN c.id IS NOT NULL AND c.status<>'Closed' THEN 1 ELSE 0 END),0) AS open_cases
FROM officers o LEFT JOIN cases c ON c.officer_id=o.id
GROUP BY o.id,o.name,o.role,o.badge;

CREATE OR REPLACE VIEW repeat_persons_view AS
SELECT p.id AS person_id,p.name,p.status,p.charge,
       COUNT(DISTINCT cp.case_reference) AS case_count
FROM persons p JOIN case_persons cp ON cp.person_id=p.id
GROUP BY p.id,p.name,p.status,p.charge
HAVING COUNT(DISTINCT cp.case_reference)>1;

-- Exposes operational case fields while omitting resolution and internal IDs.
CREATE OR REPLACE SQL SECURITY INVOKER VIEW public_case_view AS
SELECT case_ref,title,category,status,opened_on,location FROM cases;

-- Custody history is append-only even for direct SQL callers.
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
