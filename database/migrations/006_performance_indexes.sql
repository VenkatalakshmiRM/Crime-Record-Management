USE casework;

-- Apply once to existing databases; index checks make this migration safe to repeat.
SET @casework_index_ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cases' AND INDEX_NAME='idx_cases_location')=0, 'CREATE INDEX idx_cases_location ON cases(location)', 'DO 0');
PREPARE casework_index_stmt FROM @casework_index_ddl;
EXECUTE casework_index_stmt;
DEALLOCATE PREPARE casework_index_stmt;

SET @casework_index_ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cases' AND INDEX_NAME='idx_cases_status_category_opened')=0, 'CREATE INDEX idx_cases_status_category_opened ON cases(status,category,opened_on)', 'DO 0');
PREPARE casework_index_stmt FROM @casework_index_ddl;
EXECUTE casework_index_stmt;
DEALLOCATE PREPARE casework_index_stmt;

SET @casework_index_ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='persons' AND INDEX_NAME='idx_persons_name')=0, 'CREATE INDEX idx_persons_name ON persons(name)', 'DO 0');
PREPARE casework_index_stmt FROM @casework_index_ddl;
EXECUTE casework_index_stmt;
DEALLOCATE PREPARE casework_index_stmt;

SET @casework_index_ddl = IF((SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='sessions' AND INDEX_NAME='idx_sessions_user_id')=0, 'CREATE INDEX idx_sessions_user_id ON sessions(user_id)', 'DO 0');
PREPARE casework_index_stmt FROM @casework_index_ddl;
EXECUTE casework_index_stmt;
DEALLOCATE PREPARE casework_index_stmt;
