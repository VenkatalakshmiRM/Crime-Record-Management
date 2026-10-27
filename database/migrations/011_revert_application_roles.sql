-- Restore the previous Management Head / Administrator / Operator application roles.
-- Apply only to a database that previously ran 010_application_roles_and_reports.sql.

ALTER TABLE users
  MODIFY role ENUM('Admin','NCO','CID','Administrator','Management Head','Operator') NOT NULL;

UPDATE users
SET role = CASE role
  WHEN 'Admin' THEN 'Management Head'
  WHEN 'NCO' THEN 'Administrator'
  WHEN 'CID' THEN 'Operator'
  ELSE role
END;

ALTER TABLE users
  MODIFY role ENUM('Administrator','Management Head','Operator') NOT NULL;

ALTER TABLE users DROP FOREIGN KEY fk_users_officer;
ALTER TABLE users DROP COLUMN officer_id;
DELETE FROM sessions;
DROP TABLE IF EXISTS investigation_reports;
