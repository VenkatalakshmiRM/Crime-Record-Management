#!/usr/bin/env python3
"""Initialize CASEWORK's MySQL schema and verify a disposable CRUD round trip."""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / 'database' / 'schema.mysql.sql'


def load_env_file() -> None:
    """Load the project's simple KEY=VALUE .env format without dependencies."""
    env_file = ROOT / '.env'
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def report(label: str, ok: bool, detail: str = '') -> None:
    print(f"{'PASS' if ok else 'FAIL'} {label}" + (f': {detail}' if detail else ''))


def parse_mysql_script(source: str) -> list[str]:
    """Split a mysql-client script while honoring DELIMITER changes."""
    delimiter = ';'
    buffer: list[str] = []
    statements: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if not '\n'.join(buffer).strip() and stripped.upper().startswith('DELIMITER '):
            buffer.clear()
            delimiter = stripped.split(None, 1)[1]
            continue
        buffer.append(line)
        if stripped.endswith(delimiter):
            statement = '\n'.join(buffer).rstrip()
            statement = statement[:-len(delimiter)].strip()
            if statement:
                statements.append(statement)
            buffer.clear()
    if '\n'.join(buffer).strip():
        raise ValueError('SQL file ends with an incomplete statement')
    return statements


def apply_schema(connection) -> None:
    # The file contains one statement per semicolon. The database is created
    # by an administrator during setup; skip its CREATE DATABASE/USE lines so
    # the verifier needs only privileges on the configured application DB.
    statements = parse_mysql_script(SCHEMA.read_text(encoding='utf-8'))
    with connection.cursor() as cursor:
        for statement in statements:
            if re.match(r'^(CREATE\s+DATABASE|USE\s)', statement, re.IGNORECASE):
                continue
            cursor.execute(statement)
    connection.commit()


def verify_crud(connection) -> None:
    suffix = uuid.uuid4().hex[:12].upper()
    badge = f'VERIFY-{suffix}'
    case_ref = f'VERIFY-{suffix}'
    officer_id = None
    case_id = None
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO officers(name,role,badge,created_at,updated_at) VALUES(%s,%s,%s,%s,%s)',
                (f'Verification Officer {suffix}', 'Verification', badge, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'),
            )
            officer_id = cursor.lastrowid
            cursor.execute(
                'INSERT INTO cases(case_ref,title,category,status,officer_id,opened_on,location,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (case_ref, 'Disposable MySQL verification case', 'Verification', 'Active', officer_id, '2026-01-01', 'Verification only', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'),
            )
            case_id = cursor.lastrowid
        connection.commit()
        report('CRUD INSERT', True, 'temporary officer and case committed')

        with connection.cursor() as cursor:
            cursor.execute('SELECT case_ref,title,status,officer_name FROM case_view WHERE id=%s', (case_id,))
            created = cursor.fetchone()
        if not created or created['case_ref'] != case_ref or created['officer_name'] != f'Verification Officer {suffix}':
            raise RuntimeError('Inserted case or joined officer did not match expected values')
        report('CRUD SELECT / case_view JOIN', True, case_ref)

        with connection.cursor() as cursor:
            cursor.execute('UPDATE cases SET status=%s,updated_at=%s WHERE id=%s', ('Closed', '2026-01-01T00:00:00+00:00', case_id))
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute('SELECT status FROM cases WHERE id=%s', (case_id,))
            updated = cursor.fetchone()
        if not updated or updated['status'] != 'Closed':
            raise RuntimeError('Updated case status was not persisted')
        report('CRUD UPDATE', True, 'status change persisted')

        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM cases WHERE id=%s', (case_id,))
            cursor.execute('DELETE FROM officers WHERE id=%s', (officer_id,))
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) AS n FROM cases WHERE case_ref=%s', (case_ref,))
            remaining = cursor.fetchone()['n']
        if remaining:
            raise RuntimeError('Verification case remains after DELETE')
        report('CRUD DELETE', True, 'temporary records removed and confirmed absent')
    except Exception:
        connection.rollback()
        # Best-effort cleanup in case a step failed after committing inserts.
        try:
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM cases WHERE case_ref=%s', (case_ref,))
                cursor.execute('DELETE FROM officers WHERE badge=%s', (badge,))
            connection.commit()
        except Exception:
            connection.rollback()
        raise


def main() -> int:
    load_env_file()
    try:
        import pymysql
    except ImportError:
        report('PyMySQL dependency', False, 'run: pip install -r requirements.txt')
        return 1

    database = os.environ.get('DB_NAME', 'casework')
    if database != 'casework':
        report('Database name', False, 'database/schema.mysql.sql defines the fixed database `casework`; set DB_NAME=casework')
        return 1
    connection = None
    failed = False
    try:
        # Connect without selecting a DB so the schema file can create it.
        connection = pymysql.connect(
            host=os.environ.get('DB_HOST', '127.0.0.1'),
            port=int(os.environ.get('DB_PORT', '3306')),
            user=os.environ.get('DB_USER', 'casework_app'),
            password=os.environ.get('DB_PASSWORD', ''),
            database=database,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
            connect_timeout=5,
        )
        report('MySQL connection', True, f"{os.environ.get('DB_HOST', '127.0.0.1')}:{os.environ.get('DB_PORT', '3306')}")
    except Exception as exc:
        report('MySQL connection', False, str(exc))
        return 1

    try:
        try:
            apply_schema(connection)
            report('Schema initialization', True, str(SCHEMA.relative_to(ROOT)))
        except Exception as exc:
            report('Schema initialization', False, str(exc))
            failed = True
        if not failed:
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT DATABASE() AS name')
                    selected = cursor.fetchone()['name']
                if selected != database:
                    raise RuntimeError(f'schema selected {selected!r}, expected {database!r}')
                verify_crud(connection)
            except Exception as exc:
                report('CRUD round trip', False, str(exc))
                failed = True
    finally:
        connection.close()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
