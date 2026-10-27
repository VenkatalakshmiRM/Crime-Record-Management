USE casework;

-- Apply once to an installation created before Phase 9.
SET @phase9_has_last_seen = (
  SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='sessions' AND COLUMN_NAME='last_seen_at'
);
SET @phase9_alter_sessions = IF(@phase9_has_last_seen=0,
  'ALTER TABLE sessions ADD COLUMN last_seen_at VARCHAR(40) NULL', 'SELECT 1');
PREPARE phase9_stmt FROM @phase9_alter_sessions;
EXECUTE phase9_stmt;
DEALLOCATE PREPARE phase9_stmt;
UPDATE sessions SET last_seen_at=expires_at WHERE last_seen_at IS NULL;
ALTER TABLE sessions MODIFY COLUMN last_seen_at VARCHAR(40) NOT NULL;

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
