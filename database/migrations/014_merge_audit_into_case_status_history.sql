-- Preserve case snapshots and transitions in one history table, then remove audit_log.
ALTER TABLE case_status_history
  ADD COLUMN event_type VARCHAR(24) NOT NULL DEFAULT 'STATUS_CHANGED',
  ADD COLUMN old_values JSON NULL,
  ADD COLUMN new_values JSON NULL;

UPDATE case_status_history h
JOIN audit_log a
  ON a.table_name='cases'
 AND a.record_key=h.case_reference
 AND a.action='UPDATE'
 AND a.changed_at=h.changed_at
 AND JSON_UNQUOTE(JSON_EXTRACT(a.old_values,'$.status'))=h.old_status
 AND JSON_UNQUOTE(JSON_EXTRACT(a.new_values,'$.status'))=h.new_status
SET h.event_type='STATUS_CHANGED',h.old_values=a.old_values,h.new_values=a.new_values,
    h.changed_by=COALESCE(h.changed_by,a.changed_by);

INSERT INTO case_status_history(case_reference,event_type,old_status,new_status,old_values,new_values,changed_by,changed_at)
SELECT a.record_key,
       CASE WHEN a.action='INSERT' THEN 'CASE_CREATED'
            WHEN a.action='DELETE' THEN 'CASE_DELETED'
            WHEN JSON_UNQUOTE(JSON_EXTRACT(a.old_values,'$.status'))<>JSON_UNQUOTE(JSON_EXTRACT(a.new_values,'$.status')) THEN 'STATUS_CHANGED'
            ELSE 'CASE_UPDATED' END,
       CASE WHEN a.action='UPDATE' AND JSON_UNQUOTE(JSON_EXTRACT(a.old_values,'$.status'))<>JSON_UNQUOTE(JSON_EXTRACT(a.new_values,'$.status')) THEN JSON_UNQUOTE(JSON_EXTRACT(a.old_values,'$.status')) ELSE NULL END,
       CASE WHEN a.action='UPDATE' AND JSON_UNQUOTE(JSON_EXTRACT(a.old_values,'$.status'))<>JSON_UNQUOTE(JSON_EXTRACT(a.new_values,'$.status')) THEN JSON_UNQUOTE(JSON_EXTRACT(a.new_values,'$.status')) ELSE NULL END,
       a.old_values,a.new_values,a.changed_by,a.changed_at
FROM audit_log a
WHERE a.table_name='cases'
  AND NOT (a.action='UPDATE' AND JSON_UNQUOTE(JSON_EXTRACT(a.old_values,'$.status'))<>JSON_UNQUOTE(JSON_EXTRACT(a.new_values,'$.status'))
           AND EXISTS (SELECT 1 FROM case_status_history h WHERE h.case_reference=a.record_key
                       AND h.old_status=JSON_UNQUOTE(JSON_EXTRACT(a.old_values,'$.status'))
                       AND h.new_status=JSON_UNQUOTE(JSON_EXTRACT(a.new_values,'$.status'))
                       AND h.changed_at=a.changed_at));

DROP TRIGGER IF EXISTS cases_audit_insert;
DROP TRIGGER IF EXISTS cases_audit_update;
DROP TRIGGER IF EXISTS cases_audit_delete;
DROP TRIGGER IF EXISTS cases_status_history_update;
DELIMITER $$
CREATE TRIGGER cases_history_insert AFTER INSERT ON cases FOR EACH ROW
  INSERT INTO case_status_history(case_reference,event_type,new_values,changed_by,changed_at)
  VALUES(NEW.case_ref,'CASE_CREATED',JSON_OBJECT('case_ref',NEW.case_ref,'title',NEW.title,'category',NEW.category,'status',NEW.status,'officer_id',NEW.officer_id,'opened_on',NEW.opened_on,'location',NEW.location,'resolution',NEW.resolution),@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'))$$
CREATE TRIGGER cases_history_update AFTER UPDATE ON cases FOR EACH ROW
BEGIN
  IF NOT (OLD.case_ref <=> NEW.case_ref) OR NOT (OLD.title <=> NEW.title) OR NOT (OLD.category <=> NEW.category) OR NOT (OLD.status <=> NEW.status) OR NOT (OLD.officer_id <=> NEW.officer_id) OR NOT (OLD.opened_on <=> NEW.opened_on) OR NOT (OLD.location <=> NEW.location) OR NOT (OLD.resolution <=> NEW.resolution) THEN
    INSERT INTO case_status_history(case_reference,event_type,old_status,new_status,old_values,new_values,changed_by,changed_at)
    VALUES(NEW.case_ref,IF(NOT (OLD.status <=> NEW.status),'STATUS_CHANGED','CASE_UPDATED'),IF(NOT (OLD.status <=> NEW.status),OLD.status,NULL),IF(NOT (OLD.status <=> NEW.status),NEW.status,NULL),JSON_OBJECT('case_ref',OLD.case_ref,'title',OLD.title,'category',OLD.category,'status',OLD.status,'officer_id',OLD.officer_id,'opened_on',OLD.opened_on,'location',OLD.location,'resolution',OLD.resolution),JSON_OBJECT('case_ref',NEW.case_ref,'title',NEW.title,'category',NEW.category,'status',NEW.status,'officer_id',NEW.officer_id,'opened_on',NEW.opened_on,'location',NEW.location,'resolution',NEW.resolution),@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'));
  END IF;
END$$
CREATE TRIGGER cases_history_delete AFTER DELETE ON cases FOR EACH ROW
  INSERT INTO case_status_history(case_reference,event_type,old_values,changed_by,changed_at)
  VALUES(OLD.case_ref,'CASE_DELETED',JSON_OBJECT('case_ref',OLD.case_ref,'title',OLD.title,'category',OLD.category,'status',OLD.status,'officer_id',OLD.officer_id,'opened_on',OLD.opened_on,'location',OLD.location,'resolution',OLD.resolution),@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'))$$
DELIMITER ;
DROP TABLE audit_log;
