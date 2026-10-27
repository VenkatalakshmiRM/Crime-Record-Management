#!/usr/bin/env python3
"""Seed fictional CASEWORK performance data without deleting existing records."""
from __future__ import annotations

import argparse
import re
import secrets
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import api


CATEGORIES = ('Burglary', 'Fraud', 'Assault', 'Theft', 'Cybercrime')
STATUSES = ('Active', 'Under review', 'Pending', 'Closed')
LOCATIONS = tuple(f'Fictional Precinct {number:02d}' for number in range(1, 21))
ROLES = ('suspect', 'witness', 'victim', 'person_of_interest')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=int, default=10_000, help='number of cases (default: 10000)')
    parser.add_argument('--persons', type=int, default=5_000, help='number of persons (default: 5000)')
    parser.add_argument('--tag', help='optional unique alphanumeric tag; generated automatically by default')
    args = parser.parse_args()
    if args.cases < 1 or args.persons < 0:
        parser.error('--cases must be positive and --persons cannot be negative')
    tag = args.tag or secrets.token_hex(4).upper()
    if not re.fullmatch(r'[A-Za-z0-9]{1,16}', tag):
        parser.error('--tag must contain 1 to 16 letters or digits')
    tag = tag.upper()

    api.init_db()
    api.install_views()
    conn = api.connect()
    try:
        api.set_db_actor(conn, {'username': 'performance-seed'})
        cur = conn.cursor()
        prefix = f'PERF-{tag}-'
        cur.execute(api.sql('SELECT COUNT(*) AS n FROM cases WHERE case_ref LIKE ?'), (prefix + '%',))
        if api.one_dict(cur)['n']:
            raise SystemExit(f'Case prefix {prefix} already exists; choose another --tag.')
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        officer_count = min(20, max(1, (args.cases + 499) // 500))
        officer_rows = [
            (f'Perf Officer {tag}-{i + 1:02d}', 'Performance Test Detective', f'PERF-{tag}-O{i + 1:02d}', now, now)
            for i in range(officer_count)
        ]
        cur.executemany(api.sql('INSERT INTO officers(name,role,badge,created_at,updated_at) VALUES(?,?,?,?,?)'), officer_rows)
        cur.execute(api.sql('SELECT id,badge FROM officers WHERE badge LIKE ?'), (f'PERF-{tag}-O%',))
        officer_ids = [row['id'] for row in api.cursor_dicts(cur)]

        case_refs = [f'{prefix}{i + 1:05d}' for i in range(args.cases)]
        start = date(2023, 1, 1)
        case_rows = []
        for i, case_ref in enumerate(case_refs):
            case_rows.append((
                case_ref,
                f'Fictional performance case {tag}-{i + 1:05d}',
                CATEGORIES[i % len(CATEGORIES)],
                STATUSES[i % len(STATUSES)],
                officer_ids[i % len(officer_ids)],
                (start + timedelta(days=(i * 13) % 1300)).isoformat(),
                LOCATIONS[i % len(LOCATIONS)],
                None,
                now,
                now,
            ))
        cur.executemany(api.sql('INSERT INTO cases(case_ref,title,category,status,officer_id,opened_on,location,resolution,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)'), case_rows)
        cur.execute(api.sql('SELECT id,case_ref FROM cases WHERE case_ref LIKE ?'), (prefix + '%',))
        case_ids = {row['case_ref']: row['id'] for row in api.cursor_dicts(cur)}

        person_rows = []
        link_rows = []
        for i in range(args.persons):
            case_ref = case_refs[(i * 2) % len(case_refs)]
            person_rows.append((
                f'PerfSubject-{i % 10:02d}-{tag}-{i + 1:05d}',
                case_ids[case_ref],
                18 + (i % 63),
                ('Under investigation', 'In custody', 'Released on bail', 'Wanted', 'Unknown')[i % 5],
                f'Fictional performance charge {i % 37 + 1:02d}',
                now,
                now,
            ))
        if person_rows:
            cur.executemany(api.sql('INSERT INTO persons(name,case_id,age,status,charge,created_at,updated_at) VALUES(?,?,?,?,?,?,?)'), person_rows)
            cur.execute(api.sql('SELECT id,name FROM persons WHERE name LIKE ?'), (f'PerfSubject-%-{tag}-%',))
            person_ids = {row['name']: row['id'] for row in api.cursor_dicts(cur)}
            link_rows = [
                (case_refs[(i * 2) % len(case_refs)], person_ids[f'PerfSubject-{i % 10:02d}-{tag}-{i + 1:05d}'], ROLES[i % len(ROLES)], now)
                for i in range(args.persons)
            ]
            cur.executemany(api.sql('INSERT INTO case_persons(case_reference,person_id,role,added_at) VALUES(?,?,?,?)'), link_rows)
        conn.commit()
        print(f'Inserted {args.cases:,} fictional cases and {args.persons:,} fictional persons.')
        print(f'Dataset tag: {tag}')
        print('Case references: ' + prefix + '00001 through ' + prefix + f'{args.cases:05d}')
        print('Cleanup scope: cases with case_ref LIKE ' + repr(prefix + '%') + ' and people with name LIKE ' + repr(f'PerfSubject-%-{tag}-%') + '.')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    main()
