# CASEWORK new features and implementation report

## Project summary

CASEWORK is a browser-based criminal case management application backed by a Python HTTP API and a relational database. The web client uses same-origin API requests; SQLite supports local development and automated tests, and MySQL 8 is supported for deployment. See [WEB_APP_SETUP.md](WEB_APP_SETUP.md) for run configuration, [ER_DIAGRAM.md](ER_DIAGRAM.md) for relationships, and [DATA_DICTIONARY.md](DATA_DICTIONARY.md) for column definitions.

## Implemented features

- Sign-in/out, PBKDF2-HMAC-SHA256 password hashing, hashed server session tokens, role checks, account disablement, login throttling, idle and absolute session expiry, and password change.
- Management Head-only account listing, creation, role changes, enable/disable, and safeguards against self-disable or removing the last active Management Head. Administrators retain operational management access but cannot manage accounts; Operators are read-only.
- Case, person, and team-member CRUD; many-to-many case/person links with relationship roles; filtering, dashboard counts, activity history, CSV reports, and Analytics page.
- MySQL case audit and status-history triggers, closed-case deletion/reopen protections, transactional assignment/close/transfer routines, and SQLite-compatible Python services and triggers where the adapters differ.
- Workload, repeat-person, case, and public projection views; window-function analytics using RANK and LAG; performance indexes and fictional dataset/explain scripts.
- Evidence records with SHA-256 fingerprint fields and append-only custody events, plus court hearing CRUD and upcoming dashboard events.
- Optional MySQL direct database accounts for administrator, management, and SELECT-only operator access. The API itself currently uses one configured database service account.

## API additions

| Method and path | Access | Result |
|---|---|---|
| `POST /api/auth/change-password` | Signed-in user | Validates current password, updates hash, revokes all sessions for the account |
| `GET /api/users` | Management Head | Returns safe account fields only |
| `POST /api/users` | Management Head | Creates an active account with a hashed password |
| `PUT /api/users/{id}` | Management Head | Changes role and/or active state; invalidates sessions on changes |
| Existing auth login | Public | After five failed attempts for a matching username or IP, returns HTTP 429 with `Retry-After` and `login_locked` |
| Existing authenticated endpoints | Signed-in user | Enforces 30-minute idle expiry and eight-hour absolute expiry; expired session returns `session_expired` |

Earlier project endpoints include case history, assignment/closure, officer case transfer, analytics and CSV exports, evidence/custody, and court hearings; full reference is in `WEB_APP_SETUP.md`.

## Verification status

| Check | Result | Evidence / limit |
|---|---|---|
| Backend API tests | PASS — 17 tests | `python -m unittest tests.test_api -q`; SQLite temporary databases |
| MySQL schema parser/structure tests | PASS — 8 tests | `python -m unittest tests.test_mysql_script -q`; parses delimiters and checks expected DDL objects |
| Combined API and MySQL-script suite, role update | PASS — 24 tests | `python -m unittest tests.test_api tests.test_mysql_script -q`; 16 API tests and 8 schema/parser tests |
| Python syntax | PASS | `python -m py_compile backend/api.py tests/test_api.py scripts/verify_mysql.py` |
| Frontend JavaScript syntax | PASS | `node --check app.js` |
| MySQL schema delimiter/object parser | PASS — structural check only | Existing `tests.test_mysql_script` passed; this does not execute DDL or guarantee a MySQL install |
| Real MySQL 8 fresh install and CRUD | NOT RUN | MySQL client/server tools are unavailable in this environment; do not describe the schema as runtime-verified |
| Browser visual/interaction test | NOT RUN | No automated browser acceptance run was performed for this documentation phase |
| Bash script syntax and mysqldump backup/restore round trip | NOT RUN | Bash, mysql, and mysqldump are unavailable in this environment; validate against a disposable MySQL database before relying on a backup |

The MySQL parser test checks delimiter handling and key schema structure; it does not prove that MySQL accepts or executes the entire schema. A successful `/api/health` response with `adapter=mysql` and `database=connected`, followed by `scripts/verify_mysql.py` on the target MySQL instance, is required for that claim.

## Backup and restore

The scripts `scripts/backup.sh` and `scripts/restore.sh` use `mysqldump` and `mysql`. Create a dedicated client login path once with `mysql_config_editor set --login-path=casework --host=127.0.0.1 --user=casework_app --password`, then run `scripts/backup.sh path/to/casework.sql`. Restore requires an explicit `--confirm` because a standard mysqldump contains DROP TABLE statements. Additional options and cautions are in [WEB_APP_SETUP.md](WEB_APP_SETUP.md).

## Known limitations

- MySQL schema/routines have not been executed against a live MySQL server in the current verification environment.
- Application role enforcement is in the API. There is no per-request switch to `casework_admin`, `casework_management`, or `casework_operator` MySQL credentials; operator DB login is SELECT-only for separate direct clients.
- Evidence file bytes are not uploaded or managed; the application stores an approved storage path and SHA-256 fingerprint supplied by the user.
- `persons.case_id` remains as a deprecated compatibility pointer. `case_persons` is canonical for current multi-case relationships.
- The browser/API was not visually exercised for this report update. Keep local SQLite runs distinct from MySQL deployment checks.

## Demo reference

Use fictional records and show actual execution, not screenshots in place of operations.

## Phase 10 completion summary

- **Files added:** `docs/ER_DIAGRAM.md`, `docs/DATA_DICTIONARY.md`, `docs/NEW_FEATURES_REPORT.md`, `scripts/backup.sh`, and `scripts/restore.sh`.
- **Files updated:** `docs/WEB_APP_SETUP.md`.
- **API endpoints added:** none in this documentation phase; Phase 9 account and session endpoints are listed above.
- **Demo:** perform backup/restore only with MySQL client tools and a disposable target database.
- **Not verified:** live MySQL fresh install, Bash script syntax, MySQL dump/restore, and browser visual checks, because the required server/CLI/browser verification was unavailable or not run here.
