#!/usr/bin/env python3
"""Show that a failed multi-case transfer rolls back in SQLite."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import api


def assigned_counts() -> tuple[int, int]:
    conn = api.connect()
    try:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) n FROM cases c JOIN officers o ON o.id=c.officer_id WHERE o.badge=?', ('ROLLBACK-FROM',))
        source = api.one_dict(cur)['n']
        cur.execute('SELECT COUNT(*) n FROM cases c JOIN officers o ON o.id=c.officer_id WHERE o.badge=?', ('ROLLBACK-TO',))
        target = api.one_dict(cur)['n']
        return source, target
    finally:
        conn.close()


def main() -> int:
    os.environ['CASEWORK_DB'] = 'sqlite'
    with tempfile.TemporaryDirectory(prefix='.casework-rollback-', dir=ROOT / 'tests') as temp_dir:
        api.DB_PATH = Path(temp_dir) / 'rollback-demo.db'
        api.init_db()
        api.install_views()
        conn = api.connect()
        try:
            cur = conn.cursor()
            now = api.utcnow()
            cur.execute('INSERT INTO officers(name,role,badge,created_at,updated_at) VALUES(?,?,?,?,?)', ('Rollback Source', 'Demo', 'ROLLBACK-FROM', now, now))
            source_id = cur.lastrowid
            cur.execute('INSERT INTO officers(name,role,badge,created_at,updated_at) VALUES(?,?,?,?,?)', ('Rollback Destination', 'Demo', 'ROLLBACK-TO', now, now))
            target_id = cur.lastrowid
            for number in range(1, 4):
                cur.execute('INSERT INTO cases(case_ref,title,category,status,officer_id,opened_on,location,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                            (f'ROLLBACK-DEMO-{number}', f'Fictional rollback case {number}', 'Demo', 'Active', source_id, now[:10], 'Temporary database', now, now))
            cur.execute('INSERT INTO cases(case_ref,title,category,status,officer_id,opened_on,location,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                        ('ROLLBACK-TARGET-1', 'Fictional existing destination case', 'Demo', 'Active', target_id, now[:10], 'Temporary database', now, now))
            conn.commit()
        finally:
            conn.close()

        before = assigned_counts()
        print(f'Before transfer attempt: source={before[0]}, destination={before[1]}')
        conn = api.connect()
        try:
            api.service_transfer_cases(conn, 'ROLLBACK-FROM', 'ROLLBACK-TO', {'username': 'rollback_demo'}, fail_after=2)
        except RuntimeError as error:
            if 'Injected mid-transfer failure' not in str(error):
                raise
            print(f'Transfer interrupted as planned: {error}')
        finally:
            conn.close()
        after = assigned_counts()
        print(f'After rollback:          source={after[0]}, destination={after[1]}')
        if before != after:
            print('FAIL: assignments changed despite rollback')
            return 1
        print('PASS: the transaction restored every assignment to its original officer')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
