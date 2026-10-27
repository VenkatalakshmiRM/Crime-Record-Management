from __future__ import annotations
import hashlib, hmac, json, os, re, secrets, sqlite3, threading, uuid, mimetypes, argparse
from datetime import date, datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT=Path(__file__).resolve().parent.parent
for _line in (ROOT/'.env').read_text(encoding='utf-8').splitlines() if (ROOT/'.env').exists() else []:
    _line=_line.strip()
    if _line and not _line.startswith('#') and '=' in _line:
        _k,_v=_line.split('=',1);os.environ.setdefault(_k.strip(),_v.strip().strip('\"').strip("'"))
DB_PATH=Path(os.environ.get('CASEWORK_SQLITE_PATH',ROOT/'casework.db'))
SESSION_COOKIE='casework_session'
SESSION_TTL=8*60*60
SESSION_IDLE_TTL=30*60
LOGIN_WINDOW=15*60
LOGIN_MAX_ATTEMPTS=5
ROLES={'Administrator','Management Head','Operator'}
MANAGERS={'Administrator','Management Head'}
CASE_FIELDS={'id','title','category','status','officer','date','location'}
PERSON_FIELDS={'name','case','age','status','charge'}
OFFICER_FIELDS={'name','role','badge'}
CASE_STATUS={'Active','Under review','Pending','Closed'}
PERSON_STATUS={'Under investigation','In custody','Released on bail','Wanted','Unknown'}
HEARING_STATUS={'Scheduled','Completed','Adjourned','Cancelled'}
_lock=threading.RLock(); _sessions={}; _actor_context=threading.local()

def utcnow(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def hash_password(password, salt=None):
    salt=salt or secrets.token_bytes(16)
    return salt.hex()+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt,240000).hex()
def verify_password(password, stored):
    try:
        salt_hex,digest=stored.split(':',1); got=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt_hex),240000).hex(); return hmac.compare_digest(got,digest)
    except (ValueError,TypeError): return False

def connect():
    # SQLite is the isolated local/test adapter. MySQL is used when CASEWORK_DB=mysql.
    if os.environ.get('CASEWORK_DB','sqlite').lower()=='mysql':
        import pymysql
        return pymysql.connect(host=os.environ.get('DB_HOST','127.0.0.1'),port=int(os.environ.get('DB_PORT','3306')),user=os.environ.get('DB_USER','casework'),password=os.environ.get('DB_PASSWORD',''),database=os.environ.get('DB_NAME','casework'),charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False)
    conn=sqlite3.connect(DB_PATH,timeout=10); conn.row_factory=sqlite3.Row; conn.execute('PRAGMA foreign_keys=ON'); conn.create_function('casework_app_user',0,lambda:getattr(_actor_context,'username',None)); conn.create_function('days_open',1,sqlite_days_open); return conn

def sqlite_days_open(case_ref):
    conn=sqlite3.connect(DB_PATH)
    try:
        row=conn.execute('SELECT opened_on,created_at,updated_at,status FROM cases WHERE case_ref=?',(case_ref,)).fetchone()
        if not row:return 0
        start=date.fromisoformat(str(row[0] or row[1] or '')[:10]) if row[0] or row[1] else None
        closed=conn.execute("SELECT changed_at FROM case_status_history WHERE case_reference=? AND new_status='Closed' ORDER BY id DESC LIMIT 1",(case_ref,)).fetchone() if row[3]=='Closed' else None
        end=date.fromisoformat(str((closed[0] if closed else row[2]) or '')[:10]) if row[3]=='Closed' else datetime.now(timezone.utc).date()
        return max((end-start).days,0) if start else 0
    except (ValueError,TypeError):return 0
    finally:conn.close()

class CaseworkError(Exception):
    def __init__(self,status,message):self.status=status;self.message=message;super().__init__(message)

def set_db_actor(conn,user):
    if os.environ.get('CASEWORK_DB','sqlite').lower()=='mysql':conn.cursor().execute(sql('SET @app_user = ?'),(user['username'],))
    else:_actor_context.username=user['username']

def case_trigger_message(error):
    message=' '.join(str(part) for part in getattr(error,'args',())) or str(error)
    markers=('CASEWORK_CLOSED_CASE_DELETE:','CASEWORK_INVALID_STATUS_TRANSITION:','CASEWORK_CASE_NOT_FOUND:','CASEWORK_NO_OFFICERS:','CASEWORK_OFFICER_NOT_FOUND:','CASEWORK_SAME_OFFICER:','CASEWORK_CASE_ALREADY_CLOSED:','CASEWORK_TRANSFER_EMPTY:')
    for marker in markers:
        if marker in message:return message.split(marker,1)[1].strip() or marker
    return None

def db_business_error(error):
    message=case_trigger_message(error)
    if not message:return None
    status=404 if 'CASEWORK_CASE_NOT_FOUND:' in str(error) or 'CASEWORK_OFFICER_NOT_FOUND:' in str(error) else 409
    return status,message

def operation_error(error):
    if isinstance(error,CaseworkError):return error.status,error.message
    return db_business_error(error)

def sql(q):
    if os.environ.get('CASEWORK_DB','sqlite').lower()=='mysql': return q.replace('?', '%s')
    return q

def init_db():
    conn=connect()
    try:
        cur=conn.cursor()
        mysql=os.environ.get('CASEWORK_DB','sqlite').lower()=='mysql'
        if not mysql:
            cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
            user_ddl=one_dict(cur)
            if user_ddl and 'NCO' in str(user_ddl.get('sql','')):
                # Rebuild the constrained SQLite role column and revoke old sessions.
                conn.execute('PRAGMA foreign_keys=OFF');cur.execute('DROP TABLE IF EXISTS sessions');cur.execute('ALTER TABLE users RENAME TO users_legacy_roles')
        auto='INTEGER PRIMARY KEY AUTO_INCREMENT' if mysql else 'INTEGER PRIMARY KEY AUTOINCREMENT'
        case_status="ENUM('Active','Under review','Pending','Closed')" if mysql else "VARCHAR(40) CHECK(status IN ('Active','Under review','Pending','Closed'))"
        person_status="ENUM('Under investigation','In custody','Released on bail','Wanted','Unknown')" if mysql else "VARCHAR(60) CHECK(status IN ('Under investigation','In custody','Released on bail','Wanted','Unknown'))"
        user_role="ENUM('Administrator','Management Head','Operator')" if mysql else "VARCHAR(40) CHECK(role IN ('Administrator','Management Head','Operator'))"
        statements=[
        f'''CREATE TABLE IF NOT EXISTS officers(id {auto},name VARCHAR(160) NOT NULL,role VARCHAR(120) NOT NULL,badge VARCHAR(80) NOT NULL UNIQUE,created_at VARCHAR(40) NOT NULL,updated_at VARCHAR(40) NOT NULL)''',
        f'''CREATE TABLE IF NOT EXISTS users(id {auto},username VARCHAR(80) NOT NULL UNIQUE,password_hash VARCHAR(200) NOT NULL,name VARCHAR(160) NOT NULL,role {user_role} NOT NULL,active BOOLEAN NOT NULL DEFAULT TRUE,created_at VARCHAR(40) NOT NULL)''',
        f'''CREATE TABLE IF NOT EXISTS cases(id {auto},case_ref VARCHAR(80) NOT NULL UNIQUE,title VARCHAR(240) NOT NULL,category VARCHAR(100) NOT NULL,status {case_status} NOT NULL,officer_id INTEGER NULL,opened_on DATE NULL,location VARCHAR(240) NOT NULL DEFAULT '',resolution TEXT NULL,created_at VARCHAR(40) NOT NULL,updated_at VARCHAR(40) NOT NULL,FOREIGN KEY(officer_id) REFERENCES officers(id) ON DELETE SET NULL)''',
        f'''CREATE TABLE IF NOT EXISTS persons(id {auto},name VARCHAR(160) NOT NULL,case_id INTEGER NULL,age INTEGER NULL CHECK(age IS NULL OR age BETWEEN 0 AND 120),status {person_status} NOT NULL,charge VARCHAR(240) NOT NULL,created_at VARCHAR(40) NOT NULL,updated_at VARCHAR(40) NOT NULL,FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE SET NULL)''',
        f'''CREATE TABLE IF NOT EXISTS case_persons(case_reference VARCHAR(80) NOT NULL,person_id INTEGER NOT NULL,role {"ENUM('suspect','witness','victim','person_of_interest')" if mysql else "VARCHAR(32) CHECK(role IN ('suspect','witness','victim','person_of_interest'))"} NOT NULL,added_at VARCHAR(40) NOT NULL,PRIMARY KEY(case_reference,person_id,role),FOREIGN KEY(case_reference) REFERENCES cases(case_ref) ON DELETE CASCADE,FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE)''',
        f'''CREATE TABLE IF NOT EXISTS evidence(id {auto},case_reference VARCHAR(80) NOT NULL,description TEXT NOT NULL,`type` VARCHAR(80) NOT NULL,hash CHAR(64) NOT NULL,storage_path VARCHAR(500) NOT NULL,collected_by INTEGER NOT NULL,collected_at VARCHAR(40) NOT NULL,FOREIGN KEY(case_reference) REFERENCES cases(case_ref) ON DELETE RESTRICT,FOREIGN KEY(collected_by) REFERENCES officers(id) ON DELETE RESTRICT)''',
        f'''CREATE TABLE IF NOT EXISTS custody_log(id {auto},evidence_id INTEGER NOT NULL,from_officer INTEGER NULL,to_officer INTEGER NOT NULL,purpose VARCHAR(500) NOT NULL,transferred_at VARCHAR(40) NOT NULL,FOREIGN KEY(evidence_id) REFERENCES evidence(id) ON DELETE RESTRICT,FOREIGN KEY(from_officer) REFERENCES officers(id) ON DELETE RESTRICT,FOREIGN KEY(to_officer) REFERENCES officers(id) ON DELETE RESTRICT)''',
        f'''CREATE TABLE IF NOT EXISTS hearings(id {auto},case_reference VARCHAR(80) NOT NULL,court VARCHAR(240) NOT NULL,hearing_date DATE NOT NULL,status {"ENUM('Scheduled','Completed','Adjourned','Cancelled')" if mysql else "VARCHAR(24) CHECK(status IN ('Scheduled','Completed','Adjourned','Cancelled'))"} NOT NULL,outcome TEXT NULL,notes TEXT NULL,FOREIGN KEY(case_reference) REFERENCES cases(case_ref) ON DELETE RESTRICT)''',
        f'''CREATE TABLE IF NOT EXISTS activity(id {auto},action VARCHAR(60) NOT NULL,record_type VARCHAR(60) NOT NULL,record_ref VARCHAR(100) NOT NULL,description VARCHAR(300) NOT NULL,actor VARCHAR(80) NULL,created_at VARCHAR(40) NOT NULL)''',
        f'''CREATE TABLE IF NOT EXISTS audit_log(id {auto},table_name VARCHAR(64) NOT NULL,record_key VARCHAR(80) NOT NULL,action VARCHAR(10) NOT NULL,old_values {'JSON' if mysql else 'TEXT'} NULL,new_values {'JSON' if mysql else 'TEXT'} NULL,changed_by VARCHAR(80) NULL,changed_at VARCHAR(40) NOT NULL)''',
        f'''CREATE TABLE IF NOT EXISTS case_status_history(id {auto},case_reference VARCHAR(80) NOT NULL,old_status VARCHAR(40) NULL,new_status VARCHAR(40) NULL,changed_by VARCHAR(80) NULL,changed_at VARCHAR(40) NOT NULL)''',
        f'''CREATE TABLE IF NOT EXISTS sessions(token_hash VARCHAR(64) PRIMARY KEY,user_id INTEGER NOT NULL,expires_at VARCHAR(40) NOT NULL,last_seen_at VARCHAR(40) NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''',
        f'''CREATE TABLE IF NOT EXISTS login_attempts(id {auto},username_key CHAR(64) NOT NULL,ip_key CHAR(64) NOT NULL,attempted_at VARCHAR(40) NOT NULL,succeeded BOOLEAN NOT NULL DEFAULT FALSE,locked_until VARCHAR(40) NULL)''']
        for stmt in statements: cur.execute(stmt)
        if mysql:
            # Upgrade existing MySQL databases while preserving accounts and password hashes.
            cur.execute("SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users' AND COLUMN_NAME='role'")
            role_column=one_dict(cur)
            cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users' AND COLUMN_NAME='officer_id'")
            has_officer_id=bool(one_dict(cur))
            if role_column and 'NCO' in str(role_column.get('COLUMN_TYPE','')):
                cur.execute("ALTER TABLE users MODIFY role ENUM('Admin','NCO','CID','Administrator','Management Head','Operator') NOT NULL")
                cur.execute("UPDATE users SET role=CASE role WHEN 'Admin' THEN 'Management Head' WHEN 'NCO' THEN 'Administrator' WHEN 'CID' THEN 'Operator' ELSE role END")
                cur.execute("ALTER TABLE users MODIFY role ENUM('Administrator','Management Head','Operator') NOT NULL")
                if not has_officer_id:cur.execute('ALTER TABLE users ADD COLUMN officer_id BIGINT UNSIGNED NULL')
                cur.execute('DELETE FROM sessions')
                if has_officer_id:
                    cur.execute("SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users' AND COLUMN_NAME='officer_id' AND REFERENCED_TABLE_NAME IS NOT NULL")
                    officer_fk=one_dict(cur)
                    if officer_fk:cur.execute(f"ALTER TABLE users DROP FOREIGN KEY `{officer_fk['CONSTRAINT_NAME']}`")
                    cur.execute('ALTER TABLE users DROP COLUMN officer_id')
            elif has_officer_id:
                cur.execute("SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='users' AND COLUMN_NAME='officer_id' AND REFERENCED_TABLE_NAME IS NOT NULL")
                officer_fk=one_dict(cur)
                if officer_fk:cur.execute(f"ALTER TABLE users DROP FOREIGN KEY `{officer_fk['CONSTRAINT_NAME']}`")
                cur.execute('ALTER TABLE users DROP COLUMN officer_id')
            cur.execute('DROP TABLE IF EXISTS investigation_reports')
        if not mysql:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users_legacy_roles'")
            if one_dict(cur):
                cur.execute("INSERT INTO users(id,username,password_hash,name,role,active,created_at) SELECT id,username,password_hash,name,CASE role WHEN 'Admin' THEN 'Management Head' WHEN 'NCO' THEN 'Administrator' WHEN 'CID' THEN 'Operator' ELSE role END,active,created_at FROM users_legacy_roles")
                cur.execute('DROP TABLE users_legacy_roles')
            cur.execute('DROP TABLE IF EXISTS investigation_reports')
        if mysql:
            cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='sessions' AND COLUMN_NAME='last_seen_at'")
            if not one_dict(cur):cur.execute('ALTER TABLE sessions ADD COLUMN last_seen_at VARCHAR(40) NULL')
            cur.execute("UPDATE sessions SET last_seen_at=COALESCE(last_seen_at,expires_at)")
        else:
            session_columns={row['name'] for row in cur.execute('PRAGMA table_info(sessions)').fetchall()}
            if 'last_seen_at' not in session_columns:cur.execute('ALTER TABLE sessions ADD COLUMN last_seen_at VARCHAR(40) NULL')
            cur.execute('UPDATE sessions SET last_seen_at=COALESCE(last_seen_at,expires_at)')
        if mysql:
            cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='login_attempts' AND COLUMN_NAME='locked_until'")
            if not one_dict(cur):cur.execute('ALTER TABLE login_attempts ADD COLUMN locked_until VARCHAR(40) NULL')
        elif 'locked_until' not in {row['name'] for row in cur.execute('PRAGMA table_info(login_attempts)').fetchall()}:cur.execute('ALTER TABLE login_attempts ADD COLUMN locked_until VARCHAR(40) NULL')
        if mysql:
            cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cases' AND COLUMN_NAME='resolution'")
            has_resolution=one_dict(cur)
        else:has_resolution=any(row['name']=='resolution' for row in cur.execute('PRAGMA table_info(cases)').fetchall())
        if not has_resolution:cur.execute('ALTER TABLE cases ADD COLUMN resolution TEXT NULL')
        indexes=['CREATE INDEX idx_cases_status ON cases(status)','CREATE INDEX idx_cases_category ON cases(category)','CREATE INDEX idx_cases_location ON cases(location)','CREATE INDEX idx_cases_status_category_opened ON cases(status,category,opened_on)','CREATE INDEX idx_cases_officer ON cases(officer_id)','CREATE INDEX idx_persons_name ON persons(name)','CREATE INDEX idx_persons_case ON persons(case_id)','CREATE INDEX idx_persons_status ON persons(status)','CREATE INDEX idx_case_persons_person ON case_persons(person_id,case_reference)','CREATE INDEX idx_sessions_user_id ON sessions(user_id)','CREATE INDEX idx_login_attempts_username_time ON login_attempts(username_key,attempted_at)','CREATE INDEX idx_login_attempts_ip_time ON login_attempts(ip_key,attempted_at)','CREATE INDEX idx_evidence_case ON evidence(case_reference,id)','CREATE INDEX idx_evidence_collector ON evidence(collected_by)','CREATE INDEX idx_custody_evidence ON custody_log(evidence_id,id)','CREATE INDEX idx_custody_from_officer ON custody_log(from_officer)','CREATE INDEX idx_custody_to_officer ON custody_log(to_officer)','CREATE INDEX idx_hearings_case ON hearings(case_reference,hearing_date)','CREATE INDEX idx_hearings_date_status ON hearings(hearing_date,status)','CREATE INDEX idx_activity_created ON activity(created_at)','CREATE INDEX idx_audit_record ON audit_log(table_name,record_key,id)','CREATE INDEX idx_case_status_history_ref ON case_status_history(case_reference,id)']
        for stmt in indexes:
            try:cur.execute(stmt if mysql else stmt.replace('CREATE INDEX ','CREATE INDEX IF NOT EXISTS '))
            except Exception as e:
                if not (mysql and getattr(e,'args',None) and e.args[0]==1061):raise
        # Keep old records intact while migrating the deprecated single-case link.
        legacy_insert="INSERT IGNORE INTO case_persons(case_reference,person_id,role,added_at) SELECT c.case_ref,p.id,'person_of_interest',COALESCE(p.created_at,?) FROM persons p JOIN cases c ON c.id=p.case_id WHERE p.case_id IS NOT NULL" if mysql else "INSERT OR IGNORE INTO case_persons(case_reference,person_id,role,added_at) SELECT c.case_ref,p.id,'person_of_interest',COALESCE(p.created_at,?) FROM persons p JOIN cases c ON c.id=p.case_id WHERE p.case_id IS NOT NULL"
        cur.execute(sql(legacy_insert),(utcnow(),))
        if not mysql:install_sqlite_audit_triggers(cur)
        else:install_mysql_audit_triggers(cur);install_mysql_routines(cur)
        conn.commit()
        if not mysql:conn.execute('PRAGMA foreign_keys=ON')
    finally: conn.close()

def install_sqlite_audit_triggers(cur):
    stamp="strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    for name in ('cases_audit_insert','cases_audit_update','cases_audit_delete','cases_status_history_update','cases_block_closed_delete','cases_reject_reopen','custody_log_no_update','custody_log_no_delete'):
        cur.execute(f'DROP TRIGGER IF EXISTS {name}')
    cur.executescript(f'''
    CREATE TRIGGER IF NOT EXISTS cases_audit_insert AFTER INSERT ON cases BEGIN
      INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at)
      VALUES('cases',NEW.case_ref,'INSERT',NULL,json_object('case_ref',NEW.case_ref,'title',NEW.title,'category',NEW.category,'status',NEW.status,'officer_id',NEW.officer_id,'opened_on',NEW.opened_on,'location',NEW.location,'resolution',NEW.resolution),casework_app_user(),{stamp});
    END;
    CREATE TRIGGER IF NOT EXISTS cases_audit_update AFTER UPDATE ON cases BEGIN
      INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at)
      VALUES('cases',NEW.case_ref,'UPDATE',json_object('case_ref',OLD.case_ref,'title',OLD.title,'category',OLD.category,'status',OLD.status,'officer_id',OLD.officer_id,'opened_on',OLD.opened_on,'location',OLD.location,'resolution',OLD.resolution),json_object('case_ref',NEW.case_ref,'title',NEW.title,'category',NEW.category,'status',NEW.status,'officer_id',NEW.officer_id,'opened_on',NEW.opened_on,'location',NEW.location,'resolution',NEW.resolution),casework_app_user(),{stamp});
    END;
    CREATE TRIGGER IF NOT EXISTS cases_audit_delete AFTER DELETE ON cases BEGIN
      INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at)
      VALUES('cases',OLD.case_ref,'DELETE',json_object('case_ref',OLD.case_ref,'title',OLD.title,'category',OLD.category,'status',OLD.status,'officer_id',OLD.officer_id,'opened_on',OLD.opened_on,'location',OLD.location,'resolution',OLD.resolution),NULL,casework_app_user(),{stamp});
    END;
    CREATE TRIGGER IF NOT EXISTS cases_status_history_update AFTER UPDATE ON cases WHEN OLD.status IS NOT NEW.status BEGIN
      INSERT INTO case_status_history(case_reference,old_status,new_status,changed_by,changed_at)
      VALUES(NEW.case_ref,OLD.status,NEW.status,casework_app_user(),{stamp});
    END;
    CREATE TRIGGER IF NOT EXISTS cases_block_closed_delete BEFORE DELETE ON cases WHEN OLD.status='Closed' BEGIN
      SELECT RAISE(ABORT,'CASEWORK_CLOSED_CASE_DELETE: Closed cases cannot be deleted.');
    END;
    CREATE TRIGGER IF NOT EXISTS cases_reject_reopen BEFORE UPDATE OF status ON cases WHEN OLD.status='Closed' AND NEW.status<>'Closed' BEGIN
      SELECT RAISE(ABORT,'CASEWORK_INVALID_STATUS_TRANSITION: A closed case cannot be reopened or moved to another status.');
    END;
    CREATE TRIGGER IF NOT EXISTS custody_log_no_update BEFORE UPDATE ON custody_log BEGIN
      SELECT RAISE(ABORT,'CASEWORK_CUSTODY_APPEND_ONLY: Custody history cannot be updated.');
    END;
    CREATE TRIGGER IF NOT EXISTS custody_log_no_delete BEFORE DELETE ON custody_log BEGIN
      SELECT RAISE(ABORT,'CASEWORK_CUSTODY_APPEND_ONLY: Custody history cannot be deleted.');
    END;
    ''')

def install_mysql_audit_triggers(cur):
    triggers={
      'cases_audit_insert':"""CREATE TRIGGER cases_audit_insert AFTER INSERT ON cases FOR EACH ROW INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at) VALUES('cases',NEW.case_ref,'INSERT',NULL,JSON_OBJECT('case_ref',NEW.case_ref,'title',NEW.title,'category',NEW.category,'status',NEW.status,'officer_id',NEW.officer_id,'opened_on',NEW.opened_on,'location',NEW.location,'resolution',NEW.resolution),@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'))""",
      'cases_audit_update':"""CREATE TRIGGER cases_audit_update AFTER UPDATE ON cases FOR EACH ROW INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at) VALUES('cases',NEW.case_ref,'UPDATE',JSON_OBJECT('case_ref',OLD.case_ref,'title',OLD.title,'category',OLD.category,'status',OLD.status,'officer_id',OLD.officer_id,'opened_on',OLD.opened_on,'location',OLD.location,'resolution',OLD.resolution),JSON_OBJECT('case_ref',NEW.case_ref,'title',NEW.title,'category',NEW.category,'status',NEW.status,'officer_id',NEW.officer_id,'opened_on',NEW.opened_on,'location',NEW.location,'resolution',NEW.resolution),@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'))""",
      'cases_audit_delete':"""CREATE TRIGGER cases_audit_delete AFTER DELETE ON cases FOR EACH ROW INSERT INTO audit_log(table_name,record_key,action,old_values,new_values,changed_by,changed_at) VALUES('cases',OLD.case_ref,'DELETE',JSON_OBJECT('case_ref',OLD.case_ref,'title',OLD.title,'category',OLD.category,'status',OLD.status,'officer_id',OLD.officer_id,'opened_on',OLD.opened_on,'location',OLD.location,'resolution',OLD.resolution),NULL,@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ'))""",
      'cases_status_history_update':"""CREATE TRIGGER cases_status_history_update AFTER UPDATE ON cases FOR EACH ROW BEGIN IF NOT (OLD.status <=> NEW.status) THEN INSERT INTO case_status_history(case_reference,old_status,new_status,changed_by,changed_at) VALUES(NEW.case_ref,OLD.status,NEW.status,@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ')); END IF; END""",
      'cases_block_closed_delete':"""CREATE TRIGGER cases_block_closed_delete BEFORE DELETE ON cases FOR EACH ROW BEGIN IF OLD.status='Closed' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CLOSED_CASE_DELETE: Closed cases cannot be deleted.'; END IF; END""",
      'cases_reject_reopen':"""CREATE TRIGGER cases_reject_reopen BEFORE UPDATE ON cases FOR EACH ROW BEGIN IF OLD.status='Closed' AND NEW.status<>'Closed' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_INVALID_STATUS_TRANSITION: A closed case cannot be reopened or moved to another status.'; END IF; END""",
      'custody_log_no_update':"""CREATE TRIGGER custody_log_no_update BEFORE UPDATE ON custody_log FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CUSTODY_APPEND_ONLY: Custody history cannot be updated.'; END""",
      'custody_log_no_delete':"""CREATE TRIGGER custody_log_no_delete BEFORE DELETE ON custody_log FOR EACH ROW BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CUSTODY_APPEND_ONLY: Custody history cannot be deleted.'; END"""
    }
    for name,statement in triggers.items():
        cur.execute(sql('SELECT ACTION_STATEMENT FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE() AND TRIGGER_NAME=?'),(name,));existing=one_dict(cur)
        if existing and name.startswith('cases_audit_') and 'resolution' not in existing['ACTION_STATEMENT'].lower():
            cur.execute(f'DROP TRIGGER {name}');existing=None
        if not existing:cur.execute(statement)

def install_mysql_routines(cur):
    procedures={
      'assign_officer':"""CREATE PROCEDURE assign_officer(IN p_case_ref VARCHAR(80)) BEGIN DECLARE v_case_id BIGINT UNSIGNED DEFAULT NULL; DECLARE v_officer_id BIGINT UNSIGNED DEFAULT NULL; SELECT id INTO v_case_id FROM cases WHERE case_ref=p_case_ref; IF v_case_id IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CASE_NOT_FOUND: Case record was not found.'; END IF; IF (SELECT status FROM cases WHERE id=v_case_id)='Closed' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CASE_ALREADY_CLOSED: Closed cases cannot be reassigned.'; END IF; SELECT o.id INTO v_officer_id FROM officers o LEFT JOIN cases c ON c.officer_id=o.id AND c.status='Active' GROUP BY o.id ORDER BY COUNT(c.id),o.id LIMIT 1; IF v_officer_id IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_NO_OFFICERS: No team members are available for assignment.'; END IF; UPDATE cases SET officer_id=v_officer_id,updated_at=DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ') WHERE id=v_case_id; END""",
      'close_case':"""CREATE PROCEDURE close_case(IN p_case_ref VARCHAR(80),IN p_resolution TEXT,IN p_user VARCHAR(80)) BEGIN DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END; START TRANSACTION; SET @app_user=p_user; IF NOT EXISTS(SELECT 1 FROM cases WHERE case_ref=p_case_ref) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CASE_NOT_FOUND: Case record was not found.'; END IF; IF EXISTS(SELECT 1 FROM cases WHERE case_ref=p_case_ref AND status='Closed') THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_CASE_ALREADY_CLOSED: Case is already closed.'; END IF; UPDATE cases SET status='Closed',resolution=p_resolution,updated_at=DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ') WHERE case_ref=p_case_ref; INSERT INTO activity(action,record_type,record_ref,description,actor,created_at) VALUES('closed','case',p_case_ref,CONCAT('Case closed: ',p_resolution),p_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ')); COMMIT; END""",
      'transfer_officer_cases':"""CREATE PROCEDURE transfer_officer_cases(IN p_from_badge VARCHAR(80),IN p_to_badge VARCHAR(80)) BEGIN DECLARE v_from_id BIGINT UNSIGNED DEFAULT NULL; DECLARE v_to_id BIGINT UNSIGNED DEFAULT NULL; DECLARE v_moved INT DEFAULT 0; DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END; START TRANSACTION; SELECT id INTO v_from_id FROM officers WHERE badge=p_from_badge; SELECT id INTO v_to_id FROM officers WHERE badge=p_to_badge; IF v_from_id IS NULL OR v_to_id IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_OFFICER_NOT_FOUND: Source or destination team member was not found.'; END IF; IF v_from_id=v_to_id THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='CASEWORK_SAME_OFFICER: Choose a different destination team member.'; END IF; UPDATE cases SET officer_id=v_to_id,updated_at=DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ') WHERE officer_id=v_from_id; SET v_moved=ROW_COUNT(); INSERT INTO activity(action,record_type,record_ref,description,actor,created_at) VALUES('transferred','officer',p_from_badge,CONCAT('Transferred ',v_moved,' case assignments to ',p_to_badge),@app_user,DATE_FORMAT(UTC_TIMESTAMP(6),'%Y-%m-%dT%H:%i:%s.%fZ')); COMMIT; END"""
    }
    for name,statement in procedures.items():
        cur.execute(sql('SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE() AND ROUTINE_TYPE=? AND ROUTINE_NAME=?'),('PROCEDURE',name))
        if not one_dict(cur):cur.execute(statement)
    cur.execute(sql('SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=DATABASE() AND ROUTINE_TYPE=? AND ROUTINE_NAME=?'),('FUNCTION','days_open'))
    if not one_dict(cur):
        cur.execute("""CREATE FUNCTION days_open(p_case_ref VARCHAR(80)) RETURNS INT NOT DETERMINISTIC READS SQL DATA SQL SECURITY INVOKER BEGIN
          DECLARE v_open DATE DEFAULT NULL; DECLARE v_end DATE DEFAULT NULL; DECLARE v_status VARCHAR(40) DEFAULT NULL;
          SELECT COALESCE(opened_on,STR_TO_DATE(SUBSTRING(created_at,1,10),'%Y-%m-%d')),status,CURDATE() INTO v_open,v_status,v_end FROM cases WHERE case_ref=p_case_ref;
          IF v_open IS NULL THEN RETURN 0; END IF;
          IF v_status='Closed' THEN
            SELECT STR_TO_DATE(SUBSTRING(changed_at,1,10),'%Y-%m-%d') INTO v_end FROM case_status_history WHERE case_reference=p_case_ref AND new_status='Closed' ORDER BY id DESC LIMIT 1;
            IF v_end IS NULL THEN SELECT STR_TO_DATE(SUBSTRING(updated_at,1,10),'%Y-%m-%d') INTO v_end FROM cases WHERE case_ref=p_case_ref; END IF;
          END IF;
          RETURN GREATEST(DATEDIFF(COALESCE(v_end,CURDATE()),v_open),0);
        END""")

def cursor_dicts(cur):
    rows=cur.fetchall()
    return [dict(r) if isinstance(r,sqlite3.Row) else r for r in rows]
def one_dict(cur):
    r=cur.fetchone(); return (dict(r) if isinstance(r,sqlite3.Row) else r) if r else None
def json_safe(row):
    if row:
        for key,value in row.items():
            if isinstance(value,(date,datetime)):row[key]=value.isoformat()
    return row

def activity(conn,action,kind,ref,desc,actor):
    c=conn.cursor(); c.execute(sql('INSERT INTO activity(action,record_type,record_ref,description,actor,created_at) VALUES(?,?,?,?,?,?)'),(action,kind,str(ref),desc[:300],actor,utcnow()))

def service_assign_officer(conn,case_ref,user):
    try:
        conn.execute('BEGIN');cur=conn.cursor();cur.execute('SELECT id,status FROM cases WHERE case_ref=?',(case_ref,));case=one_dict(cur)
        if not case:raise CaseworkError(404,'Case record was not found.')
        if case['status']=='Closed':raise CaseworkError(409,'Closed cases cannot be reassigned.')
        cur.execute("SELECT o.id,o.name,o.badge,COUNT(c.id) active_cases FROM officers o LEFT JOIN cases c ON c.officer_id=o.id AND c.status='Active' GROUP BY o.id,o.name,o.badge ORDER BY COUNT(c.id),o.id LIMIT 1");officer=one_dict(cur)
        if not officer:raise CaseworkError(409,'No team members are available for assignment.')
        set_db_actor(conn,user);cur.execute('UPDATE cases SET officer_id=?,updated_at=? WHERE id=?',(officer['id'],utcnow(),case['id']));activity(conn,'assigned','case',case_ref,f"Case assigned to {officer['name']}",user['username']);conn.commit();return officer
    except Exception:conn.rollback();raise

def service_close_case(conn,case_ref,resolution,user):
    try:
        conn.execute('BEGIN');cur=conn.cursor();cur.execute('SELECT status FROM cases WHERE case_ref=?',(case_ref,));case=one_dict(cur)
        if not case:raise CaseworkError(404,'Case record was not found.')
        if case['status']=='Closed':raise CaseworkError(409,'Case is already closed.')
        set_db_actor(conn,user);now=utcnow();cur.execute("UPDATE cases SET status='Closed',resolution=?,updated_at=? WHERE case_ref=?",(resolution,now,case_ref));activity(conn,'closed','case',case_ref,f'Case closed: {resolution}',user['username']);conn.commit()
    except Exception:conn.rollback();raise

def service_transfer_cases(conn,from_badge,to_badge,user,fail_after=None):
    """Transfer officer assignments atomically; fail_after is demo-only fault injection."""
    try:
        conn.execute('BEGIN');cur=conn.cursor();cur.execute('SELECT id FROM officers WHERE badge=?',(from_badge,));source=one_dict(cur);cur.execute('SELECT id FROM officers WHERE badge=?',(to_badge,));target=one_dict(cur)
        if not source or not target:raise CaseworkError(404,'Source or destination team member was not found.')
        if source['id']==target['id']:raise CaseworkError(409,'Choose a different destination team member.')
        cur.execute('SELECT id FROM cases WHERE officer_id=? ORDER BY id',(source['id'],));case_ids=[row['id'] for row in cursor_dicts(cur)];set_db_actor(conn,user)
        for index,case_id in enumerate(case_ids,1):
            cur.execute('UPDATE cases SET officer_id=?,updated_at=? WHERE id=?',(target['id'],utcnow(),case_id))
            if fail_after is not None and index>=fail_after:raise RuntimeError('Injected mid-transfer failure for rollback demonstration.')
        activity(conn,'transferred','officer',from_badge,f'Transferred {len(case_ids)} case assignments to {to_badge}',user['username']);conn.commit();return len(case_ids)
    except Exception:conn.rollback();raise

def actor_from_cookie(handler):
    raw=handler.headers.get('Cookie',''); cookies=SimpleCookie();
    try: cookies.load(raw); token=cookies[SESSION_COOKIE].value
    except (KeyError,ValueError): return None
    now=datetime.now(timezone.utc); now_text=now.isoformat(timespec='seconds'); conn=connect()
    try:
        c=conn.cursor(); c.execute(sql('SELECT u.id,u.username,u.name,u.role,s.expires_at,s.last_seen_at,s.user_id FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND u.active=1'),(hashlib.sha256(token.encode()).hexdigest(),)); row=one_dict(c)
        if not row:return None
        try:expired=datetime.fromisoformat(str(row['expires_at']).replace('Z','+00:00'))<=now or datetime.fromisoformat(str(row['last_seen_at']).replace('Z','+00:00'))<=now-timedelta(seconds=SESSION_IDLE_TTL)
        except (TypeError,ValueError):expired=True
        if expired:
            c.execute(sql('DELETE FROM sessions WHERE token_hash=?'),(hashlib.sha256(token.encode()).hexdigest(),));conn.commit();handler._session_expired=True;return None
        c.execute(sql('UPDATE sessions SET last_seen_at=? WHERE token_hash=?'),(now_text,hashlib.sha256(token.encode()).hexdigest()));conn.commit()
        row.pop('expires_at',None);row.pop('last_seen_at',None);row.pop('user_id',None);return row
    finally: conn.close()

def read_body(h):
    n=int(h.headers.get('Content-Length','0'))
    if n>1000000: raise ValueError('Request body too large.')
    if not n:return {}
    try: data=json.loads(h.rfile.read(n))
    except (json.JSONDecodeError,UnicodeDecodeError): raise ValueError('Request body must be valid JSON.')
    if not isinstance(data,dict): raise ValueError('Request body must be a JSON object.')
    return data
def clean_text(data,key,label,maxlen,required=True):
    v=data.get(key,'')
    if v is None:v=''
    if not isinstance(v,str):v=str(v)
    v=v.strip()
    if required and not v: raise ValueError(f'{label} is required.')
    if len(v)>maxlen: raise ValueError(f'{label} must be {maxlen} characters or fewer.')
    return v
def fail(status,msg): return status,{'error':msg}
def authorize(user,write=False):
    if not user:return fail(401,'Please sign in to continue.')
    if write and user['role'] not in MANAGERS:return fail(403,'Your account does not have permission to make this change.')
    return None

class API(BaseHTTPRequestHandler):
    server_version='CaseworkAPI/1.0'
    def log_message(self,fmt,*args): print('%s - %s'%(self.address_string(),fmt%args))
    def send_json(self,status,payload,headers=None):
        data=json.dumps(payload,ensure_ascii=False,default=str).encode(); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store');
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(data)
    def send_bytes(self,status,data,ctype,headers=None):
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(data)
    def do_OPTIONS(self): self.send_response(204);self.send_header('Allow','GET, POST, PUT, DELETE, OPTIONS');self.end_headers()
    def do_GET(self):
        if urlparse(self.path).path.startswith('/api/'): self.route('GET')
        else: self.serve_static()
    def do_HEAD(self): self.serve_static(head=True)
    def serve_static(self,head=False):
        requested=ROOT / urlparse(self.path).path.lstrip('/')
        try:
            resolved=requested.resolve(); resolved.relative_to(ROOT.resolve())
        except (ValueError,OSError): self.send_error(404); return
        if resolved.is_dir(): resolved=resolved/'index.html'
        if not resolved.is_file(): self.send_error(404); return
        data=resolved.read_bytes(); self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(str(resolved))[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers()
        if not head:self.wfile.write(data)
    def do_POST(self): self.route('POST')
    def do_PUT(self): self.route('PUT')
    def do_DELETE(self): self.route('DELETE')
    def route(self,method):
        try:
            path=urlparse(self.path).path; query=parse_qs(urlparse(self.path).query); body=read_body(self) if method in ('POST','PUT') else {}
            status,out,headers=self.dispatch(method,path,query,body)
            if isinstance(out,bytes):self.send_bytes(status,out,headers.pop('Content-Type','text/csv; charset=utf-8'),headers)
            else:self.send_json(status,out,headers)
        except ValueError as e:self.send_json(400,{'error':str(e)})
        except sqlite3.IntegrityError as e:
            msg=str(e).lower();self.send_json(409,{'error':'That value is already in use.' if 'unique' in msg else 'The change conflicts with related records.'})
        except Exception as e:
            if e.__class__.__name__=='IntegrityError' or (getattr(e,'args',None) and e.args[0] in (1062,1451,1452)):
                self.send_json(409,{'error':'That value is already in use or conflicts with related records.'});return
            print('API error:',repr(e));self.send_json(503,{'error':'The service could not complete this request. Check the server and database configuration.'})
    def dispatch(self,m,path,q,b):
        if path=='/api/health' and m=='GET':
            try:
                c=connect();c.close();return 200,{'status':'ok','database':'connected','adapter':os.environ.get('CASEWORK_DB','sqlite').lower()},{}
            except Exception:return 503,{'status':'degraded','database':'unavailable'},{}
        if path=='/api/auth/login' and m=='POST':
            username=clean_text(b,'username','Username',80).lower();password=clean_text(b,'password','Password',200)
            c=connect()
            try:
                cur=c.cursor();now=datetime.now(timezone.utc);now_text=now.isoformat(timespec='seconds');cutoff=(now-timedelta(seconds=LOGIN_WINDOW)).isoformat(timespec='seconds');username_key=hashlib.sha256(username.encode()).hexdigest();client_ip=getattr(self,'client_address',('127.0.0.1',))[0] or 'unknown';ip_key=hashlib.sha256(client_ip.encode()).hexdigest()
                cur.execute(sql('DELETE FROM sessions WHERE expires_at<=?'),(now_text,));cur.execute(sql('DELETE FROM login_attempts WHERE attempted_at<?'),((now-timedelta(days=1)).isoformat(timespec='seconds'),))
                cur.execute(sql('SELECT MAX(locked_until) locked_until FROM login_attempts WHERE username_key=? OR ip_key=?'),(username_key,ip_key));lock_row=one_dict(cur);locked_until=lock_row['locked_until'] if lock_row else None
                if locked_until:
                    try:lock_active=datetime.fromisoformat(str(locked_until).replace('Z','+00:00'))>now
                    except ValueError:lock_active=False
                    if lock_active:
                        retry=max(1,int((datetime.fromisoformat(str(locked_until).replace('Z','+00:00'))-now).total_seconds()));c.commit();return 429,{'error':'Account or IP temporarily locked after five failed attempts. Try again in 15 minutes.','code':'login_locked'},{'Retry-After':str(retry)}
                    cur.execute(sql('DELETE FROM login_attempts WHERE (username_key=? OR ip_key=?) AND locked_until IS NOT NULL'),(username_key,ip_key))
                cur.execute(sql('SELECT COUNT(*) n FROM login_attempts WHERE succeeded=0 AND attempted_at>=? AND (username_key=? OR ip_key=?)'),(cutoff,username_key,ip_key));recent=int(one_dict(cur)['n'] or 0)
                if recent>=LOGIN_MAX_ATTEMPTS:
                    c.commit();return 429,{'error':'Account or IP temporarily locked after five failed attempts. Try again in 15 minutes.','code':'login_locked'},{'Retry-After':str(LOGIN_WINDOW)}
                cur.execute(sql('SELECT id,username,name,role,password_hash,active FROM users WHERE username=?'),(username,));u=one_dict(cur)
                if not u or not u['active'] or not verify_password(password,u['password_hash']):
                    cur.execute(sql('INSERT INTO login_attempts(username_key,ip_key,attempted_at,succeeded) VALUES(?,?,?,?)'),(username_key,ip_key,now_text,False))
                    cur.execute(sql('SELECT COUNT(*) n FROM login_attempts WHERE succeeded=0 AND attempted_at>=? AND (username_key=? OR ip_key=?)'),(cutoff,username_key,ip_key));locked=int(one_dict(cur)['n'] or 0)>=LOGIN_MAX_ATTEMPTS
                    if locked:cur.execute(sql('UPDATE login_attempts SET locked_until=? WHERE succeeded=0 AND (username_key=? OR ip_key=?)'),((now+timedelta(seconds=LOGIN_WINDOW)).isoformat(timespec='seconds'),username_key,ip_key))
                    c.commit()
                    return (429,{'error':'Account or IP temporarily locked after five failed attempts. Try again in 15 minutes.','code':'login_locked'},{'Retry-After':str(LOGIN_WINDOW)}) if locked else (401,{'error':'Username or password is incorrect.'},{})
                cur.execute(sql('DELETE FROM login_attempts WHERE username_key=? OR ip_key=?'),(username_key,ip_key));cur.execute(sql('INSERT INTO login_attempts(username_key,ip_key,attempted_at,succeeded) VALUES(?,?,?,?)'),(username_key,ip_key,now_text,True))
                token=secrets.token_urlsafe(32);expiry=(now+timedelta(seconds=SESSION_TTL)).isoformat(timespec='seconds');cur.execute(sql('INSERT INTO sessions(token_hash,user_id,expires_at,last_seen_at) VALUES(?,?,?,?)'),(hashlib.sha256(token.encode()).hexdigest(),u['id'],expiry,now_text));c.commit()
                secure='; Secure' if os.environ.get('COOKIE_SECURE','0')=='1' else ''
                return 200,{'user':{k:u[k] for k in ('username','name','role')}},{'Set-Cookie':f'{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_TTL}{secure}'}
            finally:c.close()
        if path=='/api/auth/logout' and m=='POST':
            raw=self.headers.get('Cookie','');cookies=SimpleCookie()
            try:cookies.load(raw);token=cookies[SESSION_COOKIE].value
            except Exception:token=''
            if token:
                c=connect()
                try:cur=c.cursor();cur.execute(sql('DELETE FROM sessions WHERE token_hash=?'),(hashlib.sha256(token.encode()).hexdigest(),));c.commit()
                finally:c.close()
            return 200,{'ok':True},{'Set-Cookie':f'{SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'}
        user=actor_from_cookie(self)
        if path=='/api/auth/me' and m=='GET':
            if not user:return self.session_required_response()
            return 200,{'user':{k:user[k] for k in ('username','name','role')}},{}
        auth=authorize(user)
        if auth:return self.session_required_response() if getattr(self,'_session_expired',False) else (auth[0],auth[1],{})
        if path=='/api/auth/change-password':return self.change_password(m,b,user)
        if path=='/api/users' or path.startswith('/api/users/'):
            if user['role']!='Management Head':return 403,{'error':'Management Head access is required to manage user accounts.'},{ }
            if path=='/api/users':return self.user_collection(m,b,user)
            return self.user_detail(m,path.rsplit('/',1)[-1],b,user)
        if path=='/api/dashboard' and m=='GET':
            c=connect()
            try:
                cur=c.cursor();today=date.today()
                scope='';params=()
                cur.execute(sql("SELECT COUNT(*) total,SUM(CASE WHEN status='Active' THEN 1 ELSE 0 END) active,SUM(CASE WHEN status='Under review' THEN 1 ELSE 0 END) review,SUM(CASE WHEN status='Closed' THEN 1 ELSE 0 END) closed FROM cases"+scope),params);counts=one_dict(cur) or {}
                cur.execute(sql('SELECT case_ref id,title,category,status,officer_name officer,opened_on date,location FROM case_view'+scope+' ORDER BY created_at DESC LIMIT 5'),params);recent=cursor_dicts(cur)
                hearing_scope=' AND c.officer_id=?' if scope else '';hearing_params=(today.isoformat(),(today+timedelta(days=14)).isoformat())+params
                cur.execute(sql("SELECT h.id,h.case_reference,c.title case_title,h.court,h.hearing_date,h.status FROM hearings h JOIN cases c ON c.case_ref=h.case_reference WHERE h.hearing_date>=? AND h.hearing_date<=? AND h.status IN ('Scheduled','Adjourned')"+hearing_scope+" ORDER BY h.hearing_date,h.id LIMIT 100"),hearing_params);upcoming=cursor_dicts(cur)
                return 200,{'counts':{k:int(counts.get(k) or 0) for k in ('total','active','review','closed')},'recent':[json_safe(x) for x in recent],'upcoming_hearings':[json_safe(x) for x in upcoming]},{}
            finally:c.close()
        if path=='/api/cases' and m=='GET':return self.list_cases(q,user)
        if path=='/api/cases' and m=='POST':return self.create_case(b,user)
        if path.startswith('/api/cases/') and path.endswith('/assign'):
            return self.assign_case(m,unquote(path[len('/api/cases/'): -len('/assign')].rstrip('/')),b,user)
        if path.startswith('/api/cases/') and path.endswith('/close'):
            return self.close_case_endpoint(m,unquote(path[len('/api/cases/'): -len('/close')].rstrip('/')),b,user)
        if path.startswith('/api/cases/') and path.endswith('/history'):
            ident=unquote(path[len('/api/cases/'): -len('/history')].rstrip('/'))
            return self.case_history(m,ident,user)
        if path.startswith('/api/cases/') and path.endswith('/hearings'):
            ident=unquote(path[len('/api/cases/'): -len('/hearings')].rstrip('/'))
            return self.case_hearings(m,ident,b,user)
        if path.startswith('/api/cases/') and path.endswith('/evidence'):
            ident=unquote(path[len('/api/cases/'): -len('/evidence')].rstrip('/'))
            return self.case_evidence(m,ident,b,user)
        if path.startswith('/api/evidence/') and path.endswith('/transfer'):
            ident=unquote(path[len('/api/evidence/'): -len('/transfer')].rstrip('/'))
            return self.transfer_evidence(m,ident,b,user)
        if path.startswith('/api/evidence/'):return self.evidence_detail(m,path.rsplit('/',1)[-1],b,user)
        if path.startswith('/api/hearings/'):return self.hearing_detail(m,path.rsplit('/',1)[-1],b,user)
        if path.startswith('/api/cases/'):return self.case_detail(m,unquote(path.rsplit('/',1)[-1]),b,user)
        if path=='/api/persons' and m=='GET':
            return self.list_persons(q)
        if path=='/api/persons' and m=='POST':return self.create_person(b,user)
        if path.startswith('/api/persons/'):return self.person_detail(m,path.rsplit('/',1)[-1],b,user)
        if path=='/api/officers' and m=='GET':
            return self.list_officers(q)
        if path=='/api/officers' and m=='POST':return self.create_officer(b,user)
        if path.startswith('/api/officers/') and path.endswith('/transfer-cases'):
            return self.transfer_cases_endpoint(m,unquote(path[len('/api/officers/'): -len('/transfer-cases')].rstrip('/')),b,user)
        if path.startswith('/api/officers/'):return self.officer_detail(m,path.rsplit('/',1)[-1],b,user)
        if path=='/api/activity' and m=='GET':
            c=connect()
            try:cur=c.cursor();cur.execute('SELECT action title,description detail,created_at time FROM activity ORDER BY id DESC LIMIT 100');return 200,{'items':cursor_dicts(cur)},{}
            finally:c.close()
        if path=='/api/reports' and m=='GET':
            return self.report(q)
        if path=='/api/analytics' and m=='GET':
            return self.analytics(q)
        if path=='/api/reports/export' and m=='GET':
            return self.export(q)
        return 404,{'error':'Endpoint not found.'},{}
    def session_required_response(self):
        if getattr(self,'_session_expired',False):
            return 401,{'error':'Your session has expired. Please sign in again.','code':'session_expired'},{'Set-Cookie':f'{SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'}
        return 401,{'error':'Please sign in to continue.'},{}
    def change_password(self,m,b,user):
        if m!='POST':return 405,{'error':'Method not allowed.'},{ }
        current=clean_text(b,'current_password','Current password',200);new=clean_text(b,'new_password','New password',200)
        if len(new)<12:raise ValueError('New password must be at least 12 characters long.')
        if hmac.compare_digest(current,new):raise ValueError('New password must be different from the current password.')
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT password_hash FROM users WHERE id=? AND active=1'),(user['id'],));row=one_dict(cur)
            if not row or not verify_password(current,row['password_hash']):return 400,{'error':'Current password is incorrect.'},{ }
            cur.execute(sql('UPDATE users SET password_hash=? WHERE id=?'),(hash_password(new),user['id']));cur.execute(sql('DELETE FROM sessions WHERE user_id=?'),(user['id'],));activity(c,'changed_password','user',user['username'],'Account password changed',user['username']);c.commit()
            return 200,{'ok':True,'message':'Password changed. Please sign in again.'},{'Set-Cookie':f'{SESSION_COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'}
        except Exception:c.rollback();raise
        finally:c.close()
    def user_collection(self,m,b,user):
        if m=='GET':
            c=connect()
            try:cur=c.cursor();cur.execute('SELECT id,username,name,role,active,created_at FROM users ORDER BY name,id');return 200,{'items':cursor_dicts(cur)},{}
            finally:c.close()
        if m!='POST':return 405,{'error':'Method not allowed.'},{}
        username=clean_text(b,'username','Username',80).lower();name=clean_text(b,'name','Name',160);password=clean_text(b,'password','Password',200);role=clean_text(b,'role','Role',40)
        if not re.fullmatch(r'[a-z0-9._-]+',username):raise ValueError('Username may contain lowercase letters, numbers, periods, underscores, and hyphens.')
        if len(password)<12:raise ValueError('Password must be at least 12 characters long.')
        if role not in ROLES:raise ValueError('Unsupported account role.')
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('INSERT INTO users(username,password_hash,name,role,active,created_at) VALUES(?,?,?,?,?,?)'),(username,hash_password(password),name,role,True,utcnow()));uid=cur.lastrowid;activity(c,'created','user',username,f'Created {role} account',user['username']);c.commit();return 201,{'item':{'id':uid,'username':username,'name':name,'role':role,'active':True}},{ }
        except Exception:c.rollback();raise
        finally:c.close()
    def user_detail(self,m,ident,b,user):
        if m not in ('PUT','DELETE'):return 405,{'error':'Method not allowed.'},{ }
        try:uid=int(ident)
        except ValueError:return 404,{'error':'User account was not found.'},{ }
        if m=='DELETE':
            c=connect()
            try:
                cur=c.cursor();cur.execute(sql('SELECT id,username,name,role,active FROM users WHERE id=?'),(uid,));existing=one_dict(cur)
                if not existing:return 404,{'error':'User account was not found.'},{ }
                if uid==user['id']:return 409,{'error':'You cannot delete your own account.'},{ }
                if existing['role']=='Management Head' and bool(existing['active']):
                    cur.execute("SELECT COUNT(*) n FROM users WHERE role='Management Head' AND active=1");heads=int(one_dict(cur)['n'] or 0)
                    if heads<=1:return 409,{'error':'At least one active Management Head account must remain.'},{ }
                cur.execute(sql('DELETE FROM sessions WHERE user_id=?'),(uid,))
                cur.execute(sql('DELETE FROM users WHERE id=?'),(uid,))
                activity(c,'deleted','user',existing['username'],'Deleted user account',user['username']);c.commit()
                return 200,{'ok':True,'message':'User account deleted.'},{ }
            except Exception:c.rollback();raise
            finally:c.close()
        role=b.get('role');active=b.get('active')
        if role is None and active is None:return 400,{'error':'Provide a role or active state to update.'},{ }
        if role is not None and role not in ROLES:raise ValueError('Unsupported account role.')
        if active is not None:
            if isinstance(active,bool):active_value=active
            elif active in (0,1,'0','1'):active_value=bool(int(active))
            else:raise ValueError('Active state must be true or false.')
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT id,username,name,role,active,created_at FROM users WHERE id=?'),(uid,));existing=one_dict(cur)
            if not existing:return 404,{'error':'User account was not found.'},{ }
            next_role=role or existing['role'];next_active=active_value if active is not None else bool(existing['active'])
            if uid==user['id'] and not next_active:return 409,{'error':'You cannot disable your own Management Head account.'},{ }
            if uid==user['id'] and next_role!='Management Head':return 409,{'error':'You cannot change your own Management Head role.'},{ }
            if existing['role']=='Management Head' and bool(existing['active']) and (next_role!='Management Head' or not next_active):
                cur.execute("SELECT COUNT(*) n FROM users WHERE role='Management Head' AND active=1");heads=int(one_dict(cur)['n'] or 0)
                if heads<=1:return 409,{'error':'At least one active Management Head account must remain.'},{ }
            changed=next_role!=existing['role'] or next_active!=bool(existing['active'])
            cur.execute(sql('UPDATE users SET role=?,active=? WHERE id=?'),(next_role,next_active,uid))
            if changed:cur.execute(sql('DELETE FROM sessions WHERE user_id=?'),(uid,))
            activity(c,'updated','user',existing['username'],'Updated account role or access state',user['username']);c.commit();existing['role']=next_role;existing['active']=next_active;return 200,{'item':existing},{ }
        except Exception:c.rollback();raise
        finally:c.close()
    def list_cases(self,q,user):
        c=connect()
        try:
            terms=[];vals=[];search=(q.get('q') or [''])[0].strip();status=(q.get('status') or [''])[0];category=(q.get('category') or [''])[0]
            if search:terms.append('(case_ref LIKE ? OR title LIKE ? OR category LIKE ? OR location LIKE ? OR officer_name LIKE ?)');vals.extend([f'%{search}%']*5)
            if status:terms.append('status=?');vals.append(status)
            if category:terms.append('category=?');vals.append(category)
            where=(' WHERE '+' AND '.join(terms)) if terms else '';cur=c.cursor();cur.execute('SELECT COUNT(*) n FROM case_view'+where,vals);total=one_dict(cur)['n'];limit=min(max(int((q.get('limit') or ['100'])[0]),1),250);offset=max(int((q.get('offset') or ['0'])[0]),0);cur.execute('SELECT case_ref id,id db_id,title,category,status,officer_id,officer_name officer,opened_on date,location,resolution,created_at,updated_at FROM case_view'+where+' ORDER BY created_at DESC LIMIT ? OFFSET ?',vals+[limit,offset]);return 200,{'items':[json_safe(x) for x in cursor_dicts(cur)],'total':total},{}
        finally:c.close()
    def create_case(self,b,user):
        denied=authorize(user,True)
        if denied:return denied[0],denied[1],{}
        d={k:clean_text(b,k,label,maxlen) for k,label,maxlen in [('id','Case reference',80),('title','Case title',240),('category','Category',100),('status','Status',40)]};d['location']=clean_text(b,'location','Location',240,False);off=clean_text(b,'officer','Assigned officer',160,False);opened=clean_text(b,'date','Date opened',10,False)
        if d['status'] not in CASE_STATUS:raise ValueError('Unsupported case status.')
        if opened:
            try:date.fromisoformat(opened)
            except ValueError:raise ValueError('Date opened must use YYYY-MM-DD format.')
        c=connect()
        try:
            set_db_actor(c,user);cur=c.cursor();oid=None
            if off:
                cur.execute(sql('SELECT id FROM officers WHERE name=? OR badge=?'),(off,off));row=one_dict(cur)
                if not row:return 400,{'error':'Assigned officer was not found. Choose a team member from the directory.'},{}
                oid=row['id']
            now=utcnow();cur.execute(sql('INSERT INTO cases(case_ref,title,category,status,officer_id,opened_on,location,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)'),(d['id'],d['title'],d['category'],d['status'],oid,opened or None,d['location'],now,now));ref=d['id'];activity(c,'created','case',ref,f'Case record registered: {d["title"]}',user['username']);c.commit();return 201,{'item':self.get_case(c,ref)},{}
        except Exception:
            c.rollback();raise
        finally:c.close()
    def assign_case(self,m,ref,b,user):
        if m!='POST':return 405,{'error':'Method not allowed.'},{}
        denied=authorize(user,True)
        if denied:return denied[0],denied[1],{}
        c=connect()
        try:
            if b.get('officer_id'):
                cur=c.cursor();cur.execute(sql('SELECT id,name,badge FROM officers WHERE id=?'),(int(b['officer_id']),));officer=one_dict(cur)
                if not officer:return 404,{'error':'Team member was not found.'},{}
                set_db_actor(c,user);cur.execute(sql('UPDATE cases SET officer_id=?,updated_at=? WHERE case_ref=?'),(officer['id'],utcnow(),ref))
                if not cur.rowcount:return 404,{'error':'Case record was not found.'},{}
                activity(c,'assigned','case',ref,f"Case assigned to {officer['name']}",user['username']);c.commit()
                return 200,{'assigned_officer':officer['name'],'case_reference':ref},{ }
            if os.environ.get('CASEWORK_DB','sqlite').lower()=='mysql':
                set_db_actor(c,user);cur=c.cursor();cur.execute(sql('CALL assign_officer(?)'),(ref,))
                while cur.nextset():pass
                cur.execute(sql('SELECT o.id,o.name,o.badge,(SELECT COUNT(*) FROM cases ac WHERE ac.officer_id=o.id AND ac.status=?) active_cases FROM cases ca JOIN officers o ON o.id=ca.officer_id WHERE ca.case_ref=?'),('Active',ref));officer=one_dict(cur)
                if not officer:raise CaseworkError(404,'Case record was not found.')
                activity(c,'assigned','case',ref,f"Case assigned to {officer['name']}",user['username']);c.commit()
            else:officer=service_assign_officer(c,ref,user)
            cur=c.cursor();cur.execute(sql('SELECT case_ref id,title,status,officer_name officer,opened_on date,location,resolution FROM case_view WHERE case_ref=?'),(ref,));record=json_safe(one_dict(cur));return 200,{'item':record,'assigned_officer':officer['name']},{}
        except Exception as error:
            c.rollback();mapped=operation_error(error)
            if mapped:return mapped[0],{'error':mapped[1]},{}
            raise
        finally:c.close()
    def close_case_endpoint(self,m,ref,b,user):
        if m!='POST':return 405,{'error':'Method not allowed.'},{}
        denied=authorize(user,True)
        if denied:return denied[0],denied[1],{}
        resolution=clean_text(b,'resolution','Resolution',2000)
        c=connect()
        try:
            if os.environ.get('CASEWORK_DB','sqlite').lower()=='mysql':
                cur=c.cursor();cur.execute(sql('CALL close_case(?,?,?)'),(ref,resolution,user['username']))
                while cur.nextset():pass
            else:service_close_case(c,ref,resolution,user)
            cur=c.cursor();cur.execute(sql('SELECT case_ref id,title,status,officer_name officer,opened_on date,location,resolution FROM case_view WHERE case_ref=?'),(ref,));record=json_safe(one_dict(cur));
            if os.environ.get('CASEWORK_DB','sqlite').lower()=='mysql':c.commit()
            return 200,{'item':record},{}
        except Exception as error:
            c.rollback();mapped=operation_error(error)
            if mapped:return mapped[0],{'error':mapped[1]},{}
            raise
        finally:c.close()
    def transfer_cases_endpoint(self,m,ident,b,user):
        if m!='POST':return 405,{'error':'Method not allowed.'},{}
        denied=authorize(user,True)
        if denied:return denied[0],denied[1],{}
        to_badge=clean_text(b,'to_badge','Destination badge ID',80)
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT id,badge FROM officers WHERE id=?'),(ident,));source=one_dict(cur)
            if not source:return 404,{'error':'Source team member was not found.'},{}
            if os.environ.get('CASEWORK_DB','sqlite').lower()=='mysql':
                cur.execute(sql('SELECT COUNT(*) moved FROM cases WHERE officer_id=?'),(source['id'],));moved=one_dict(cur)['moved'];set_db_actor(c,user);cur.execute(sql('CALL transfer_officer_cases(?,?)'),(source['badge'],to_badge))
                while cur.nextset():pass
                c.commit()
            else:moved=service_transfer_cases(c,source['badge'],to_badge,user)
            return 200,{'ok':True,'moved':moved,'from_badge':source['badge'],'to_badge':to_badge},{}
        except Exception as error:
            c.rollback();mapped=operation_error(error)
            if mapped:return mapped[0],{'error':mapped[1]},{}
            raise
        finally:c.close()
    def get_case(self,c,ref):
        cur=c.cursor();cur.execute(sql('SELECT case_ref id,id db_id,title,category,status,officer_id,officer_name officer,opened_on date,location,resolution,created_at,updated_at FROM case_view WHERE case_ref=?'),(ref,));return json_safe(one_dict(cur))
    def case_history(self,m,ref,user):
        if m!='GET':return 405,{'error':'Method not allowed.'},{}
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT case_ref,officer_id FROM cases WHERE case_ref=?'),(ref,));case=one_dict(cur)
            cur.execute(sql('SELECT action,old_values,new_values,changed_by,changed_at FROM audit_log WHERE table_name=? AND record_key=? ORDER BY id'),('cases',ref));audit=cursor_dicts(cur)
            cur.execute(sql('SELECT old_status,new_status,changed_by,changed_at FROM case_status_history WHERE case_reference=? ORDER BY id'),(ref,));statuses=cursor_dicts(cur)
            items=[{'type':'record','action':row['action'],'old_values':row['old_values'],'new_values':row['new_values'],'changed_by':row['changed_by'],'changed_at':row['changed_at']} for row in audit]
            items.extend({'type':'status','action':'STATUS','old_status':row['old_status'],'new_status':row['new_status'],'changed_by':row['changed_by'],'changed_at':row['changed_at']} for row in statuses)
            items.sort(key=lambda row:row['changed_at'] or '',reverse=True)
            return 200,{'case_reference':ref,'items':items},{}
        finally:c.close()
    def case_detail(self,m,ident,b,user):
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT case_ref,officer_id FROM cases WHERE case_ref=? OR CAST(id AS CHAR)=?'),(ident,ident));found=one_dict(cur)
            if not found:return 404,{'error':'Case record was not found.'},{}
            ref=found['case_ref']
            if m=='GET':return 200,{'item':self.get_case(c,ref)},{}
            denied=authorize(user,True)
            if denied:return denied[0],denied[1],{}
            if m=='DELETE':
                set_db_actor(c,user)
                cur.execute(sql('DELETE FROM cases WHERE case_ref=?'),(ref,));activity(c,'deleted','case',ref,'Case record deleted',user['username']);c.commit();return 200,{'ok':True},{}
            if m=='PUT':
                old=self.get_case(c,ref);d={k:clean_text(b,k,label,maxlen) for k,label,maxlen in [('title','Case title',240),('category','Category',100),('status','Status',40)]};d['location']=clean_text(b,'location','Location',240,False);off=clean_text(b,'officer','Assigned officer',160,False);opened=clean_text(b,'date','Date opened',10,False)
                if d['status'] not in CASE_STATUS:raise ValueError('Unsupported case status.')
                if opened:
                    try:date.fromisoformat(opened)
                    except ValueError:raise ValueError('Date opened must use YYYY-MM-DD format.')
                oid=None
                if off:
                    cur.execute(sql('SELECT id FROM officers WHERE name=? OR badge=?'),(off,off));o=one_dict(cur)
                    if not o:return 400,{'error':'Assigned officer was not found.'},{}
                    oid=o['id']
                set_db_actor(c,user);cur.execute(sql('UPDATE cases SET title=?,category=?,status=?,officer_id=?,opened_on=?,location=?,updated_at=? WHERE case_ref=?'),(d['title'],d['category'],d['status'],oid,opened or None,d['location'],utcnow(),ref));activity(c,'updated','case',ref,f'Case record updated: {old["status"]} to {d["status"]}',user['username']);c.commit();return 200,{'item':self.get_case(c,ref)},{}
            return 405,{'error':'Method not allowed.'},{}
        except Exception as error:
            c.rollback();message=case_trigger_message(error)
            if message:return 409,{'error':message},{}
            raise
        finally:c.close()
    def list_persons(self,q):
        c=connect()
        try:
            cur=c.cursor();s=(q.get('q') or [''])[0].strip();st=(q.get('status') or [''])[0];where=[];v=[]
            if s:where.append('(p.name LIKE ? OR p.charge LIKE ? OR EXISTS(SELECT 1 FROM case_persons cp WHERE cp.person_id=p.id AND cp.case_reference LIKE ?))');v.extend([f'%{s}%']*3)
            if st:where.append('p.status=?');v.append(st)
            sqlq='SELECT p.id FROM persons p'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY p.id DESC';cur.execute(sql(sqlq),v);items=[self.person_item(c,row['id']) for row in cursor_dicts(cur)];return 200,{'items':items},{}
        finally:c.close()
    def normalize_person_links(self, body, default_role='person_of_interest'):
        allowed={'suspect','witness','victim','person_of_interest'}
        if 'cases' not in body:
            legacy=clean_text(body,'case','Related case',80,False)
            return ([{'case_reference':legacy,'role':default_role}] if legacy else []),True
        raw=body.get('cases')
        if not isinstance(raw,list):raise ValueError('Linked cases must be a list.')
        links=[];seen=set()
        for item in raw:
            if not isinstance(item,dict):raise ValueError('Each linked case must include a case reference and role.')
            ref=str(item.get('case_reference',item.get('case',''))).strip();role=str(item.get('role','person_of_interest')).strip()
            if not ref:continue
            if len(ref)>80:raise ValueError('Case reference is too long.')
            if role not in allowed:raise ValueError('Unsupported person role for case.')
            pair=(ref,role)
            if pair not in seen:links.append({'case_reference':ref,'role':role});seen.add(pair)
        return links,False
    def replace_person_links(self,c,pid,links):
        cur=c.cursor();resolved=[]
        for link in links:
            cur.execute(sql('SELECT case_ref,id FROM cases WHERE case_ref=?'),(link['case_reference'],));case=one_dict(cur)
            if not case:return None
            resolved.append((case['case_ref'],case['id'],link['role']))
        cur.execute(sql('SELECT case_reference,role FROM case_persons WHERE person_id=?'),(pid,));existing={(row['case_reference'],row['role']) for row in cursor_dicts(cur)}
        desired={(ref,role) for ref,_,role in resolved}
        for ref,role in existing-desired:cur.execute(sql('DELETE FROM case_persons WHERE case_reference=? AND person_id=? AND role=?'),(ref,pid,role))
        now=utcnow()
        for ref,_,role in resolved:
            if (ref,role) not in existing:cur.execute(sql('INSERT INTO case_persons(case_reference,person_id,role,added_at) VALUES(?,?,?,?)'),(ref,pid,role,now))
        legacy_id=resolved[0][1] if resolved else None
        cur.execute(sql('UPDATE persons SET case_id=? WHERE id=?'),(legacy_id,pid))
        return True
    def create_person(self,b,user):
        denied=authorize(user,True)
        if denied:return denied[0],denied[1],{}
        d={k:clean_text(b,k,label,maxlen) for k,label,maxlen in [('name','Name',160),('status','Status',60),('charge','Primary charge',240)]};links,_=self.normalize_person_links(b);age=b.get('age')
        if d['status'] not in PERSON_STATUS:raise ValueError('Unsupported person status.')
        age=int(age) if age not in (None,'',chr(8212)) else None
        if age is not None and not 0<=age<=120:raise ValueError('Age must be between 0 and 120.')
        c=connect()
        try:
            cur=c.cursor();resolved=[]
            for link in links:
                cur.execute(sql('SELECT id FROM cases WHERE case_ref=?'),(link['case_reference'],));found=one_dict(cur)
                if not found:return 400,{'error':f"Related case {link['case_reference']} was not found."},{}
                resolved.append((link,found['id']))
            now=utcnow();legacy_id=resolved[0][1] if resolved else None
            cur.execute(sql('INSERT INTO persons(name,case_id,age,status,charge,created_at,updated_at) VALUES(?,?,?,?,?,?,?)'),(d['name'],legacy_id,age,d['status'],d['charge'],now,now));pid=cur.lastrowid
            for link,_ in resolved:cur.execute(sql('INSERT INTO case_persons(case_reference,person_id,role,added_at) VALUES(?,?,?,?)'),(link['case_reference'],pid,link['role'],now))
            activity(c,'created','person',pid,'Person of interest added',user['username']);c.commit();return 201,{'item':self.person_item(c,pid)},{}
        except Exception:c.rollback();raise
        finally:c.close()
    def person_item(self,c,pid):
        cur=c.cursor();cur.execute(sql('SELECT p.id,p.name,p.case_id,p.age,p.status,p.charge FROM persons p WHERE p.id=?'),(pid,));item=one_dict(cur)
        if not item:return None
        legacy_id=item.pop('case_id');cur.execute(sql('SELECT cp.case_reference,cp.role,cp.added_at FROM case_persons cp WHERE cp.person_id=? ORDER BY cp.case_reference,cp.role'),(pid,));links=cursor_dicts(cur)
        # Prefer the legacy pointer for the old `case` property, while returning all canonical links.
        case_ref=None
        if legacy_id is not None:cur.execute(sql('SELECT case_ref FROM cases WHERE id=?'),(legacy_id,));legacy=one_dict(cur);case_ref=legacy['case_ref'] if legacy else None
        if case_ref is None and links:case_ref=links[0]['case_reference']
        item['case']=case_ref;item['cases']=links
        return item
    def person_detail(self,m,ident,b,user):
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT id FROM persons WHERE id=?'),(ident,));r=one_dict(cur)
            if not r:return 404,{'error':'Person record was not found.'},{}
            if m=='GET':return 200,{'item':self.person_item(c,r['id'])},{}
            denied=authorize(user,True)
            if denied:return denied[0],denied[1],{}
            if m=='DELETE':cur.execute(sql('DELETE FROM persons WHERE id=?'),(r['id'],));activity(c,'deleted','person',ident,'Person of interest deleted',user['username']);c.commit();return 200,{'ok':True},{}
            if m=='PUT':
                d={k:clean_text(b,k,label,maxlen) for k,label,maxlen in [('name','Name',160),('status','Status',60),('charge','Primary charge',240)]};links,_=self.normalize_person_links(b);age=b.get('age');age=int(age) if age not in (None,'',chr(8212)) else None
                if d['status'] not in PERSON_STATUS:raise ValueError('Unsupported person status.')
                if age is not None and not 0<=age<=120:raise ValueError('Age must be between 0 and 120.')
                if self.replace_person_links(c,r['id'],links) is None:return 400,{'error':'A linked case was not found.'},{}
                cur.execute(sql('UPDATE persons SET name=?,age=?,status=?,charge=?,updated_at=? WHERE id=?'),(d['name'],age,d['status'],d['charge'],utcnow(),r['id']));activity(c,'updated','person',ident,'Person of interest updated',user['username']);c.commit();return 200,{'item':self.person_item(c,r['id'])},{}
            return 405,{'error':'Method not allowed.'},{}
        except Exception:c.rollback();raise
        finally:c.close()
    def evidence_item(self,c,evidence_id):
        cur=c.cursor();cur.execute(sql('SELECT e.id,e.case_reference,e.description,e.`type`,e.hash,e.storage_path,e.collected_by,e.collected_at,o.name collected_by_name,o.badge collected_by_badge FROM evidence e JOIN officers o ON o.id=e.collected_by WHERE e.id=?'),(evidence_id,));item=one_dict(cur)
        if not item:return None
        cur.execute(sql('''SELECT cl.id,cl.from_officer,fo.name from_officer_name,cl.to_officer,too.name to_officer_name,
          cl.purpose,cl.transferred_at FROM custody_log cl LEFT JOIN officers fo ON fo.id=cl.from_officer
          JOIN officers too ON too.id=cl.to_officer WHERE cl.evidence_id=? ORDER BY cl.id'''),(evidence_id,));transfers=cursor_dicts(cur)
        timeline=[{'id':None,'from_officer':None,'from_officer_name':None,'to_officer':item['collected_by'],'to_officer_name':item['collected_by_name'],'purpose':'Evidence collected','transferred_at':item['collected_at'],'event':'collected'}]
        timeline.extend({**entry,'event':'transfer'} for entry in transfers);item['custody_timeline']=timeline
        return item
    def case_evidence(self,m,ref,b,user):
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT case_ref,officer_id FROM cases WHERE case_ref=?'),(ref,));case=one_dict(cur)
            if not case:return 404,{'error':'Case record was not found.'},{}
            if m=='GET':
                cur.execute(sql('SELECT id FROM evidence WHERE case_reference=? ORDER BY collected_at DESC,id DESC'),(ref,));return 200,{'case_reference':ref,'items':[self.evidence_item(c,row['id']) for row in cursor_dicts(cur)]},{}
            if m!='POST':return 405,{'error':'Method not allowed.'},{}
            denied=authorize(user,True)
            if denied:return denied[0],denied[1],{}
            description=clean_text(b,'description','Evidence description',4000);kind=clean_text(b,'type','Evidence type',80);digest=clean_text(b,'hash','SHA-256 hash',64).lower();storage_path=clean_text(b,'storage_path','Storage path',500)
            if not re.fullmatch(r'[0-9a-f]{64}',digest):raise ValueError('Evidence hash must be a 64-character SHA-256 hexadecimal digest.')
            collector=str(b.get('collected_by','')).strip()
            if not collector:raise ValueError('Choose the officer who collected the evidence.')
            if collector.isdigit():cur.execute(sql('SELECT id FROM officers WHERE id=?'),(int(collector),))
            else:cur.execute(sql('SELECT id FROM officers WHERE badge=?'),(collector,))
            officer=one_dict(cur)
            if not officer:return 400,{'error':'The collecting officer was not found.'},{}
            now=utcnow();cur.execute(sql('INSERT INTO evidence(case_reference,description,`type`,hash,storage_path,collected_by,collected_at) VALUES(?,?,?,?,?,?,?)'),(ref,description,kind,digest,storage_path,officer['id'],now));evidence_id=cur.lastrowid
            activity(c,'created','evidence',evidence_id,f'Evidence recorded for case {ref}',user['username']);c.commit();return 201,{'item':self.evidence_item(c,evidence_id)},{}
        except Exception:c.rollback();raise
        finally:c.close()
    def evidence_detail(self,m,ident,b,user):
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT e.id,e.hash,c.officer_id FROM evidence e JOIN cases c ON c.case_ref=e.case_reference WHERE e.id=?'),(ident,));row=one_dict(cur)
            if not row:return 404,{'error':'Evidence record was not found.'},{}
            if m=='GET':return 200,{'item':self.evidence_item(c,row['id'])},{}
            denied=authorize(user,True)
            if denied:return denied[0],denied[1],{}
            if m=='PUT':
                digest=str(b.get('hash',row['hash'])).strip().lower()
                if digest!=row['hash'].strip().lower():return 409,{'error':'The SHA-256 evidence fingerprint is immutable after collection.'},{}
                description=clean_text(b,'description','Evidence description',4000);kind=clean_text(b,'type','Evidence type',80);storage_path=clean_text(b,'storage_path','Storage path',500)
                cur.execute(sql('UPDATE evidence SET description=?,`type`=?,storage_path=? WHERE id=?'),(description,kind,storage_path,row['id']));activity(c,'updated','evidence',row['id'],'Evidence metadata updated',user['username']);c.commit();return 200,{'item':self.evidence_item(c,row['id'])},{}
            if m=='DELETE':
                cur.execute(sql('SELECT COUNT(*) n FROM custody_log WHERE evidence_id=?'),(row['id'],))
                if one_dict(cur)['n']:return 409,{'error':'Evidence with custody transfers cannot be deleted; its chain-of-custody history must be retained.'},{}
                cur.execute(sql('DELETE FROM evidence WHERE id=?'),(row['id'],));activity(c,'deleted','evidence',row['id'],'Evidence record deleted before transfer',user['username']);c.commit();return 200,{'ok':True},{}
            return 405,{'error':'Method not allowed.'},{}
        except Exception:c.rollback();raise
        finally:c.close()
    def transfer_evidence(self,m,ident,b,user):
        if m!='POST':return 405,{'error':'Method not allowed.'},{}
        denied=authorize(user,True)
        if denied:return denied[0],denied[1],{}
        purpose=clean_text(b,'purpose','Transfer purpose',500);target=str(b.get('to_officer','')).strip()
        if not target:raise ValueError('Choose the receiving officer.')
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT id,collected_by FROM evidence WHERE id=?'),(ident,));item=one_dict(cur)
            if not item:return 404,{'error':'Evidence record was not found.'},{}
            if target.isdigit():cur.execute(sql('SELECT id FROM officers WHERE id=?'),(int(target),))
            else:cur.execute(sql('SELECT id FROM officers WHERE badge=?'),(target,))
            recipient=one_dict(cur)
            if not recipient:return 400,{'error':'The receiving officer was not found.'},{}
            cur.execute(sql('SELECT to_officer FROM custody_log WHERE evidence_id=? ORDER BY id DESC LIMIT 1'),(item['id'],));last=one_dict(cur);from_id=last['to_officer'] if last else item['collected_by']
            if from_id==recipient['id']:return 409,{'error':'Evidence is already held by that officer.'},{}
            now=utcnow();cur.execute(sql('INSERT INTO custody_log(evidence_id,from_officer,to_officer,purpose,transferred_at) VALUES(?,?,?,?,?)'),(item['id'],from_id,recipient['id'],purpose,now));activity(c,'transferred','evidence',item['id'],f"Evidence transferred to officer {recipient['id']}",user['username']);c.commit();return 200,{'item':self.evidence_item(c,item['id'])},{}
        except Exception:c.rollback();raise
        finally:c.close()
    def hearing_values(self,b):
        court=clean_text(b,'court','Court',240);hearing_date=clean_text(b,'hearing_date','Hearing date',10);status=clean_text(b,'status','Hearing status',24)
        try:
            parsed=date.fromisoformat(hearing_date)
            if parsed.isoformat()!=hearing_date:raise ValueError()
        except ValueError:raise ValueError('Hearing date must use YYYY-MM-DD format.')
        if status not in HEARING_STATUS:raise ValueError('Unsupported hearing status.')
        outcome=clean_text(b,'outcome','Outcome',4000,False);notes=clean_text(b,'notes','Notes',8000,False)
        return court,hearing_date,status,outcome or None,notes or None
    def hearing_item(self,c,hearing_id):
        cur=c.cursor();cur.execute(sql('SELECT h.id,h.case_reference,c.title case_title,h.court,h.hearing_date,h.status,h.outcome,h.notes FROM hearings h JOIN cases c ON c.case_ref=h.case_reference WHERE h.id=?'),(hearing_id,));return json_safe(one_dict(cur))
    def case_hearings(self,m,ref,b,user):
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT case_ref,officer_id FROM cases WHERE case_ref=?'),(ref,));case=one_dict(cur)
            if not case:return 404,{'error':'Case record was not found.'},{}
            if m=='GET':
                cur.execute(sql('SELECT id FROM hearings WHERE case_reference=? ORDER BY hearing_date,id'),(ref,));return 200,{'case_reference':ref,'items':[self.hearing_item(c,row['id']) for row in cursor_dicts(cur)]},{}
            if m!='POST':return 405,{'error':'Method not allowed.'},{}
            denied=authorize(user,True)
            if denied:return denied[0],denied[1],{}
            values=self.hearing_values(b);cur.execute(sql('INSERT INTO hearings(case_reference,court,hearing_date,status,outcome,notes) VALUES(?,?,?,?,?,?)'),(ref,*values));hearing_id=cur.lastrowid;activity(c,'created','hearing',hearing_id,f"Court hearing scheduled for case {ref}",user['username']);c.commit();return 201,{'item':self.hearing_item(c,hearing_id)},{}
        except Exception:c.rollback();raise
        finally:c.close()
    def hearing_detail(self,m,ident,b,user):
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT h.id,h.case_reference,c.officer_id FROM hearings h JOIN cases c ON c.case_ref=h.case_reference WHERE h.id=?'),(ident,));row=one_dict(cur)
            if not row:return 404,{'error':'Hearing record was not found.'},{}
            if m=='GET':return 200,{'item':self.hearing_item(c,row['id'])},{}
            denied=authorize(user,True)
            if denied:return denied[0],denied[1],{}
            if m=='PUT':
                values=self.hearing_values(b);cur.execute(sql('UPDATE hearings SET court=?,hearing_date=?,status=?,outcome=?,notes=? WHERE id=?'),(*values,row['id']));activity(c,'updated','hearing',row['id'],f"Court hearing updated for case {row['case_reference']}",user['username']);c.commit();return 200,{'item':self.hearing_item(c,row['id'])},{}
            if m=='DELETE':
                cur.execute(sql('DELETE FROM hearings WHERE id=?'),(row['id'],));activity(c,'deleted','hearing',row['id'],f"Court hearing deleted for case {row['case_reference']}",user['username']);c.commit();return 200,{'ok':True},{}
            return 405,{'error':'Method not allowed.'},{}
        except Exception:c.rollback();raise
        finally:c.close()
    def list_officers(self,q):
        c=connect()
        try:
            cur=c.cursor();s=(q.get('q') or [''])[0].strip();role=(q.get('role') or [''])[0];where=[];v=[]
            if s:where.append('(o.name LIKE ? OR o.badge LIKE ? OR o.role LIKE ?)');v.extend([f'%{s}%']*3)
            if role:where.append('o.role=?');v.append(role)
            cur.execute(sql('SELECT o.id,o.name,o.role,o.badge,(SELECT COUNT(*) FROM cases c WHERE c.officer_id=o.id) cases FROM officers o'+((' WHERE '+' AND '.join(where)) if where else '')+' ORDER BY o.name'),v);return 200,{'items':cursor_dicts(cur)},{}
        finally:c.close()
    def create_officer(self,b,user):
        denied=authorize(user,True)
        if denied:return denied[0],denied[1],{}
        d={k:clean_text(b,k,label,maxlen) for k,label,maxlen in [('name','Name',160),('role','Role',120),('badge','Badge ID',80)]};c=connect()
        try:
            cur=c.cursor();now=utcnow();cur.execute(sql('INSERT INTO officers(name,role,badge,created_at,updated_at) VALUES(?,?,?,?,?)'),(d['name'],d['role'],d['badge'],now,now));oid=cur.lastrowid;activity(c,'created','officer',oid,'Team member added',user['username']);c.commit();cur.execute(sql('SELECT o.id,o.name,o.role,o.badge,(SELECT COUNT(*) FROM cases c WHERE c.officer_id=o.id) cases FROM officers o WHERE id=?'),(oid,));return 201,{'item':one_dict(cur)},{}
        finally:c.close()
    def officer_detail(self,m,ident,b,user):
        c=connect()
        try:
            cur=c.cursor();cur.execute(sql('SELECT id FROM officers WHERE id=?'),(ident,));o=one_dict(cur)
            if not o:return 404,{'error':'Team member was not found.'},{}
            if m=='GET':cur.execute(sql('SELECT o.id,o.name,o.role,o.badge,(SELECT COUNT(*) FROM cases c WHERE c.officer_id=o.id) cases FROM officers o WHERE id=?'),(o['id'],));return 200,{'item':one_dict(cur)},{}
            denied=authorize(user,True)
            if denied:return denied[0],denied[1],{}
            if m=='DELETE':cur.execute(sql('SELECT COUNT(*) n FROM cases WHERE officer_id=?'),(o['id'],));
            if m=='DELETE' and one_dict(cur)['n']:return 409,{'error':'This team member is assigned to cases. Reassign those cases before deleting.'},{}
            if m=='DELETE':cur.execute(sql('DELETE FROM officers WHERE id=?'),(o['id'],));activity(c,'deleted','officer',ident,'Team member deleted',user['username']);c.commit();return 200,{'ok':True},{}
            if m=='PUT':
                d={k:clean_text(b,k,label,maxlen) for k,label,maxlen in [('name','Name',160),('role','Role',120),('badge','Badge ID',80)]};cur.execute(sql('UPDATE officers SET name=?,role=?,badge=?,updated_at=? WHERE id=?'),(d['name'],d['role'],d['badge'],utcnow(),o['id']));activity(c,'updated','officer',ident,'Team member updated',user['username']);c.commit();cur.execute(sql('SELECT o.id,o.name,o.role,o.badge,(SELECT COUNT(*) FROM cases c WHERE c.officer_id=o.id) cases FROM officers o WHERE id=?'),(o['id'],));return 200,{'item':one_dict(cur)},{}
            return 405,{'error':'Method not allowed.'},{}
        except Exception:c.rollback();raise
        finally:c.close()
    def report(self,q):
        c=connect()
        try:
            cur=c.cursor();cur.execute('SELECT status,COUNT(*) count FROM cases GROUP BY status');statuses=cursor_dicts(cur);cur.execute('SELECT COUNT(*) total FROM cases');total=one_dict(cur)['total'];cur.execute('SELECT COUNT(*) n FROM activity');activities=one_dict(cur)['n'];cur.execute('SELECT o.name,COUNT(c.id) cases FROM officers o LEFT JOIN cases c ON c.officer_id=o.id GROUP BY o.id,o.name ORDER BY o.name');workload=cursor_dicts(cur);cur.execute('SELECT location,COUNT(*) cases FROM cases GROUP BY location ORDER BY location');locations=cursor_dicts(cur);cur.execute('SELECT case_ref case_reference,title,status FROM cases ORDER BY case_ref');aging=cursor_dicts(cur)
            for item in aging:cur.execute(sql('SELECT days_open(?) days_open'),(item['case_reference'],));item['days_open']=one_dict(cur)['days_open']
            aging.sort(key=lambda item:(-item['days_open'],item['case_reference']));return 200,{'total':total,'statuses':statuses,'activities':activities,'workload':workload,'locations':locations,'case_aging':aging,'adapter':os.environ.get('CASEWORK_DB','sqlite').lower()},{}
        finally:c.close()
    def analytics_rows(self,c):
        cur=c.cursor()
        cur.execute('SELECT officer_id,officer_name,closed_cases,RANK() OVER (ORDER BY closed_cases DESC) `rank` FROM officer_workload_view ORDER BY `rank`,officer_name');officers=cursor_dicts(cur)
        if os.environ.get('CASEWORK_DB','sqlite').lower()=='mysql':month_expr="DATE_FORMAT(STR_TO_DATE(SUBSTRING(created_at,1,19),'%Y-%m-%dT%H:%i:%s'),'%Y-%m')"
        else:month_expr="strftime('%Y-%m',created_at)"
        cur.execute(f'''WITH monthly AS (SELECT {month_expr} month,COUNT(*) case_count FROM cases GROUP BY {month_expr})
          SELECT month,case_count,LAG(case_count) OVER (ORDER BY month) previous_month_cases,
          case_count-LAG(case_count) OVER (ORDER BY month) case_change
          FROM monthly ORDER BY month''');monthly=cursor_dicts(cur)
        for row in monthly:
            row['case_change']=row['case_change'] if row['case_change'] is not None else 0
        cur.execute(sql('SELECT location,COUNT(*) case_count FROM cases WHERE TRIM(location)<>? GROUP BY location HAVING COUNT(*)>=? ORDER BY case_count DESC,location'),('',2));hotspots=cursor_dicts(cur)
        return {'officer_rankings':officers,'monthly_case_change':monthly,'location_hotspots':hotspots}
    def analytics(self,q):
        c=connect()
        try:return 200,self.analytics_rows(c),{}
        finally:c.close()
    def export(self,q):
        import csv,io
        c=connect()
        try:
            cur=c.cursor();kind=(q.get('type') or ['cases'])[0]
            if kind in ('analytics-officers','analytics-monthly','analytics-hotspots'):
                data=self.analytics_rows(c);key={'analytics-officers':'officer_rankings','analytics-monthly':'monthly_case_change','analytics-hotspots':'location_hotspots'}[kind];rows=data[key]
            elif kind=='summary':cur.execute('SELECT status,COUNT(*) case_count FROM cases GROUP BY status ORDER BY status')
            elif kind=='resolution':cur.execute("SELECT status,COUNT(*) case_count FROM cases WHERE status IN ('Closed','Under review') GROUP BY status ORDER BY status")
            elif kind=='aging':
                cur.execute('SELECT case_ref case_reference,title,status,resolution FROM cases ORDER BY case_ref');rows=cursor_dicts(cur)
                for row in rows:cur.execute(sql('SELECT days_open(?) days_open'),(row['case_reference'],));row['days_open']=one_dict(cur)['days_open']
                rows.sort(key=lambda row:(-row['days_open'],row['case_reference']))
            elif kind=='locations':cur.execute('SELECT location,COUNT(*) case_count FROM cases GROUP BY location ORDER BY location')
            elif kind=='activity':cur.execute('SELECT action,record_type,record_ref,description,actor,created_at FROM activity ORDER BY id DESC')
            elif kind=='people':
                cur.execute('SELECT id FROM persons ORDER BY id');rows=[]
                for item in cursor_dicts(cur):
                    person=self.person_item(c,item['id']);rows.append({'id':person['id'],'name':person['name'],'related_cases':'; '.join(f"{link['case_reference']} ({link['role']})" for link in person['cases']),'age':person['age'],'status':person['status'],'charge':person['charge']})
            elif kind=='officers':cur.execute('SELECT name,role,badge,(SELECT COUNT(*) FROM cases c WHERE c.officer_id=o.id) assigned_cases FROM officers o ORDER BY name')
            else:cur.execute('SELECT case_ref case_reference,title,category,status,officer_name officer,opened_on date,location FROM case_view ORDER BY created_at DESC')
            if kind not in ('aging','analytics-officers','analytics-monthly','analytics-hotspots'):rows=cursor_dicts(cur)
            buf=__import__('io').StringIO();writer=csv.DictWriter(buf,fieldnames=list(rows[0].keys()) if rows else ['No records']);writer.writeheader();writer.writerows(rows) if rows else None;return 200,buf.getvalue().encode('utf-8-sig'),{'Content-Type':'text/csv; charset=utf-8','Content-Disposition':f'attachment; filename="casework-{kind}.csv"'}
        finally:c.close()

def install_views():
    # Shared views keep joins, workload summaries, and data exposure consistent.
    c=connect()
    try:
        cur=c.cursor()
        for name in ('repeat_persons_view','officer_workload_view','public_case_view','case_view'):cur.execute(f'DROP VIEW IF EXISTS {name}')
        cur.execute('CREATE VIEW case_view AS SELECT c.id,c.case_ref,c.title,c.category,c.status,c.officer_id,o.name officer_name,c.opened_on,c.location,c.resolution,c.created_at,c.updated_at FROM cases c LEFT JOIN officers o ON o.id=c.officer_id')
        cur.execute('''CREATE VIEW officer_workload_view AS SELECT o.id officer_id,o.name officer_name,o.role,o.badge,COUNT(c.id) total_cases,COALESCE(SUM(CASE WHEN c.status='Closed' THEN 1 ELSE 0 END),0) closed_cases,COALESCE(SUM(CASE WHEN c.id IS NOT NULL AND c.status<>'Closed' THEN 1 ELSE 0 END),0) open_cases FROM officers o LEFT JOIN cases c ON c.officer_id=o.id GROUP BY o.id,o.name,o.role,o.badge''')
        cur.execute('''CREATE VIEW repeat_persons_view AS SELECT p.id person_id,p.name,p.status,p.charge,COUNT(DISTINCT cp.case_reference) case_count FROM persons p JOIN case_persons cp ON cp.person_id=p.id GROUP BY p.id,p.name,p.status,p.charge HAVING COUNT(DISTINCT cp.case_reference)>1''')
        cur.execute('''CREATE VIEW public_case_view AS SELECT case_ref,title,category,status,opened_on,location FROM cases''')
        c.commit()
    finally:c.close()
def create_user_from_env():
    username=os.environ.get('CASEWORK_NEW_USER','').strip().lower();password=os.environ.get('CASEWORK_NEW_PASSWORD','');name=os.environ.get('CASEWORK_NEW_NAME','').strip();role=os.environ.get('CASEWORK_NEW_ROLE','Operator').strip()
    if not username or not password or not name:raise RuntimeError('Set CASEWORK_NEW_USER, CASEWORK_NEW_PASSWORD, and CASEWORK_NEW_NAME.')
    if role not in ROLES:raise RuntimeError('CASEWORK_NEW_ROLE must be Management Head, Administrator, or Operator.')
    if len(password)<12:raise RuntimeError('Use a unique password with at least 12 characters.')
    c=connect()
    try:
        cur=c.cursor();cur.execute(sql('SELECT id FROM users WHERE username=?'),(username,))
        if one_dict(cur):raise RuntimeError('Username already exists; refusing to overwrite it.')
        cur.execute(sql('INSERT INTO users(username,password_hash,name,role,active,created_at) VALUES(?,?,?,?,?,?)'),(username,hash_password(password),name,role,True,utcnow()));c.commit()
    finally:c.close()
def seed_sample():
    c=connect()
    try:
        cur=c.cursor();cur.execute('SELECT COUNT(*) n FROM cases');
        if one_dict(cur)['n']:raise RuntimeError('Sample data is only added to an empty cases table.')
        now=utcnow();officers=[('Maya Thompson','Senior Detective','DEMO-1042'),('Arjun Patel','Investigation Officer','DEMO-1087'),('Jordan Chen','Detective','DEMO-1136')]
        for name,role,badge in officers:cur.execute(sql('INSERT INTO officers(name,role,badge,created_at,updated_at) VALUES(?,?,?,?,?)'),(name,role,badge,now,now))
        cur.execute('SELECT id,name FROM officers');ids={r['name']:r['id'] for r in cursor_dicts(cur)}
        cases=[('DEMO-2026-001','Riverside warehouse report','Burglary','Active','Maya Thompson','Riverside'),('DEMO-2026-002','Central district fraud report','Fraud','Under review','Arjun Patel','Central District'),('DEMO-2026-003','Market street incident','Assault','Pending','Jordan Chen','Market Street')]
        for ref,title,cat,status,officer,location in cases:cur.execute(sql('INSERT INTO cases(case_ref,title,category,status,officer_id,opened_on,location,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)'),(ref,title,cat,status,ids[officer],date.today().isoformat(),location,now,now))
        cur.execute(sql('SELECT id,case_ref FROM cases WHERE case_ref=?'),('DEMO-2026-001',));linked=one_dict(cur);cur.execute(sql('INSERT INTO persons(name,case_id,age,status,charge,created_at,updated_at) VALUES(?,?,?,?,?,?,?)'),('Taylor Reed',linked['id'],34,'Under investigation','Breaking and entering',now,now));person_id=cur.lastrowid;cur.execute(sql("INSERT INTO case_persons(case_reference,person_id,role,added_at) VALUES(?,?,?,?)"),(linked['case_ref'],person_id,'person_of_interest',now));c.commit()
    finally:c.close()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--create-user',action='store_true',help='Create a user from CASEWORK_NEW_* environment variables');parser.add_argument('--seed-sample',action='store_true',help='Add fictional examples to an empty database');args=parser.parse_args();init_db();install_views()
    if args.create_user:create_user_from_env();print('User created.')
    elif args.seed_sample:seed_sample();print('Fictional sample records added.')
    else:
        host=os.environ.get('HOST','127.0.0.1');port=int(os.environ.get('PORT','8010'));adapter=os.environ.get('CASEWORK_DB','sqlite').lower();database=DB_PATH if adapter=='sqlite' else os.environ.get('DB_NAME','casework');server=ThreadingHTTPServer((host,port),API);print(f'Casework serving on http://{host}:{port} ({adapter} adapter; database={database}; cookie_secure={os.environ.get("COOKIE_SECURE","0")})',flush=True);server.serve_forever()
if __name__=='__main__':main()
