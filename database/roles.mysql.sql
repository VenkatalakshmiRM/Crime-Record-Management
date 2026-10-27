-- Optional MySQL accounts for direct database access and least-privilege demos.
-- Replace each password placeholder with a unique, strong secret before running.
-- The HTTP API currently uses the single DB_USER configured in .env; it does
-- not switch MySQL credentials based on CASEWORK application-user roles.

CREATE USER IF NOT EXISTS 'casework_admin'@'localhost' IDENTIFIED BY 'REPLACE_WITH_ADMIN_SECRET';
CREATE USER IF NOT EXISTS 'casework_management'@'localhost' IDENTIFIED BY 'REPLACE_WITH_MANAGEMENT_SECRET';
CREATE USER IF NOT EXISTS 'casework_operator'@'localhost' IDENTIFIED BY 'REPLACE_WITH_OPERATOR_SECRET';

REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'casework_admin'@'localhost';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'casework_management'@'localhost';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'casework_operator'@'localhost';

-- Administrator account: schema maintenance and full application access.
GRANT ALL PRIVILEGES ON casework.* TO 'casework_admin'@'localhost';

-- Management account: application data read/write; no account/privilege administration.
GRANT SELECT, INSERT, UPDATE, DELETE ON casework.* TO 'casework_management'@'localhost';

-- Operator account: read-only database access.
GRANT SELECT ON casework.* TO 'casework_operator'@'localhost';
