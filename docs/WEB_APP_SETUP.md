# CASEWORK Browser Application — Setup and API

## Current architecture

The existing CASEWORK HTML, CSS, and JavaScript UI is now served by `backend/api.py`. The Python standard-library HTTP server serves the static files and `/api/*` routes. Persistent cases, persons of interest, officers, users, sessions, and activity are read from a SQL database through the API. SQLite is the dependency-free local/test adapter; MySQL is supported for database configuration and deployment. The old Java Swing application remains a separate client/database implementation and does not share browser sessions or data automatically.

`database/schema.mysql.sql` documents the MySQL schema. The API initializes tables, `case_view`, and case audit triggers when it starts. The SQL file is also suitable for manual review and initialization. Do not run this against a database containing unrelated tables named `cases`, `persons`, etc.

## Requirements

- Python 3.10 or newer.
- MySQL 8.0+ for MySQL mode, plus an account with rights to create/use the application database and tables.
- `requirements.txt` (PyMySQL) when using MySQL. SQLite mode uses Python's standard library and needs no installed packages.

## Quick start (isolated SQLite development)

Open PowerShell in the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
$env:CASEWORK_DB = 'sqlite'
$env:CASEWORK_SQLITE_PATH = "$PWD\casework.db"
$env:CASEWORK_NEW_USER = 'casework_admin'
$env:CASEWORK_NEW_NAME = 'Casework Administrator'
$env:CASEWORK_NEW_ROLE = 'Management Head'
$env:CASEWORK_NEW_PASSWORD = 'choose-a-unique-password-at-least-12-chars'
python backend/api.py --create-user
python backend/api.py --seed-sample
python backend/api.py
```

The sample command only runs when the cases table is empty. It inserts fictional DEMO records and a demo officer/person. Start the site at [http://localhost:8010](http://localhost:8010) and sign in with the username/password you chose. SQLite mode exercises the actual API and persistence but is not MySQL connectivity proof.

For the existing local database, use an account provisioned in that database. For a new database, create a Management Head using the environment-variable workflow above and choose a unique password.

## MySQL setup

1. Install and start MySQL Server 8.0+. Open a MySQL administrative shell (for example, MySQL Workbench or `mysql -u root -p`) and create the dedicated application account. Choose a strong local password and use it consistently below:

```sql
CREATE DATABASE IF NOT EXISTS casework CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'casework_app'@'localhost' IDENTIFIED BY 'replace-with-a-strong-local-password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES, DROP, CREATE VIEW, SHOW VIEW, TRIGGER, EXECUTE, CREATE ROUTINE, ALTER ROUTINE ON casework.* TO 'casework_app'@'localhost';
```

Run this as a MySQL administrator. The application account is limited to the `casework` database and needs table/view DDL privileges because the API initializes them at startup. Keep it dedicated to this project. `database/schema.mysql.sql` documents and creates/selects the fixed database name `casework`; the verifier skips its database-selection statements and applies the tables and view within the already-created database.

2. In the repository root, create a virtual environment, install the MySQL connector, and configure the application. The setup commands are for PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set the following values to match your MySQL setup. Keep `.env` private; it is ignored by Git. The API and verification script read it directly without a dotenv package.

```dotenv
CASEWORK_DB=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=casework
DB_USER=casework_app
DB_PASSWORD=your-local-password
COOKIE_SECURE=0
```

3. For an existing Phase 2 database, apply the Phase 3 upgrade once before starting the updated API:

```powershell
mysql -u casework_app -p casework < database/migrations/003_routines_transactions.sql
```

Apply later numbered migrations in order when upgrading an existing database. Phase 6 adds the performance indexes in `database/migrations/006_performance_indexes.sql`; a fresh install uses `database/schema.mysql.sql` and already includes them.

Phase 7 adds evidence and custody tracking. For an existing installation, apply `database/migrations/007_evidence_custody.sql` after earlier migrations and restart the API. Fresh schema installs include these tables and append-only triggers.

Phase 8 adds court hearings. Apply `database/migrations/008_court_hearings.sql` to an existing database after earlier migrations, or use the complete schema for a fresh install. Hearing records are managed per case at `/api/cases/{reference}/hearings`; the dashboard returns scheduled or adjourned hearings between today and 14 days ahead.

For a fresh installation, use the complete `database/schema.mysql.sql` instead; it already includes the resolution field and routines. Then verify a real MySQL CRUD round trip from the repository root:

```powershell
python scripts/verify_mysql.py
```

The script connects using `.env`, applies `database/schema.mysql.sql` tables, view, triggers, procedures, and function, then creates, reads (including the `case_view` join), updates, and deletes uniquely named temporary verification records. It prints PASS/FAIL for the connection, schema initialization, and each CRUD operation. Successful verification requires every step to print `PASS`; a failed step exits nonzero. The records are committed and then removed by the script. The database itself must already exist, and the configured account must have the listed privileges on `casework`.

4. Provision an administrator without embedding a credential in source code:

```powershell
$env:CASEWORK_NEW_USER = 'your-admin-name'
$env:CASEWORK_NEW_NAME = 'Your Management Head Name'
$env:CASEWORK_NEW_ROLE = 'Management Head'
$securePassword = Read-Host 'Enter a unique password (12+ characters)' -AsSecureString
$env:CASEWORK_NEW_PASSWORD = [System.Net.NetworkCredential]::new('', $securePassword).Password
Remove-Variable securePassword
python backend/api.py --create-user
Remove-Item Env:\CASEWORK_NEW_PASSWORD
```

The CLI refuses to replace an existing username. Set `CASEWORK_NEW_ROLE` to `Management Head`, `Administrator`, or `Operator` to create the corresponding role account. There is intentionally no public signup route; the Management Head creates subsequent accounts from User management.

5. Start the API and frontend together:

```powershell
python backend/api.py
```

## Health / connection verification

Open `http://localhost:8010/api/health`. In MySQL mode, the required response is `{"status":"ok","database":"connected","adapter":"mysql"}`. Verify that `adapter` is `mysql` and `database` is `connected`; SQLite health is not MySQL proof. The verification script's CRUD checks are additional evidence, but the live health response is the definitive check that the running API selected and connected to MySQL. On failure, inspect the server console and check `.env`, the MySQL service, grants, and schema. Neither check returns credentials.

## API endpoint reference

All data endpoints except health and login/logout require a valid server session cookie. The cookie is HTTP-only, `SameSite=Strict`, and expires after eight hours. Write methods require Administrator or Management Head. Operators are read-only.

| Method         | Endpoint                              | Purpose                                                                      |
| -------------- | ------------------------------------- | ---------------------------------------------------------------------------- |
| GET            | `/api/health`                         | Service and configured database-adapter health                               |
| POST           | `/api/auth/login`                     | Authenticate `{username,password}`; returns role identity and session cookie |
| POST           | `/api/auth/logout`                    | Invalidate server session and clear cookie                                   |
| GET            | `/api/auth/me`                        | Return current authenticated identity                                        |
| POST           | `/api/auth/change-password`           | Change the signed-in user's password and revoke their sessions               |
| GET/POST       | `/api/users`                          | Management Head-only user list or account creation                           |
| PUT            | `/api/users/{id}`                     | Management Head-only role or active-state change                             |
| GET            | `/api/dashboard`                      | Database counts and five most recent cases                                   |
| GET/POST       | `/api/cases`                          | Search/list (q,status,category,limit,offset) or create case                  |
| GET/PUT/DELETE | `/api/cases/{case-reference}`         | Retrieve, update, or delete one case                                         |
| GET            | `/api/cases/{case-reference}/history` | Retrieve record audit and status history timeline                            |
| POST           | `/api/cases/{reference}/assign`       | Assign the least-loaded officer based on active cases                        |
| POST           | `/api/cases/{reference}/close`        | Close a case and save its resolution atomically                              |
| GET/POST       | `/api/persons`                        | Search/list or create person of interest                                     |
| GET/PUT/DELETE | `/api/persons/{id}`                   | Retrieve, update, or delete person                                           |
| GET/POST       | `/api/officers`                       | Search/list (q,role) or create team member                                   |
| GET/PUT/DELETE | `/api/officers/{id}`                  | Retrieve, update, or delete team member                                      |
| POST           | `/api/officers/{id}/transfer-cases`   | Atomically transfer all assignments to `{to_badge}`                          |
| GET            | `/api/reports`                        | Counts, status summary, activity count, workload, locations                  |
| GET            | `/api/reports/export?type=...`        | CSV: cases, summary, resolution, locations, activity, workload               |
| GET            | `/api/activity`                       | Recent server-recorded activity                                              |

Responses use JSON objects with `item`, `items`, `counts`, or `error` fields as appropriate. HTTP 400 reports validation errors, 401 requires sign-in, 403 means role is not permitted, 404 means the record/route is absent, 409 means a uniqueness or relationship conflict, 429 means the login account or IP is temporarily locked, and 503 means the backend/database could not complete the request.

## Role matrix

| Capability                                             | Management Head | Administrator | Operator |
| ------------------------------------------------------ | --------------: | ------------: | -------: |
| Read cases, people, team, reports, activity            |             Yes |           Yes |      Yes |
| Create/update/delete cases                             |             Yes |           Yes |       No |
| Create/update/delete persons                           |             Yes |           Yes |       No |
| Create/update/delete team                              |             Yes |           Yes |       No |
| Manage user accounts (list/create/change role/disable) |             Yes |            No |       No |
| Manage own account/change password                     |             Yes |           Yes |      Yes |

The hierarchy is Management Head → Administrator → Operator. The Management Head has all application permissions, including user management. Administrators can manage cases, persons, team members, evidence, and hearings, but cannot manage accounts. Operators are read-only and cannot change cases, persons, team members, or accounts. The API enforces permissions even if a user bypasses the UI. New accounts require a 12-character password. A Management Head cannot disable or demote their own account or remove the final active Management Head.

If a database previously ran `database/migrations/010_application_roles_and_reports.sql`, apply `database/migrations/011_revert_application_roles.sql` before continuing. The API also maps the temporary role values back during startup; SQLite keeps existing users and password hashes, expires old sessions, and removes the temporary report table and officer link.

## Phase 9 security controls

- Login failures are stored in `login_attempts`. The table stores SHA-256 keys for the normalized username and client IP, not the raw IP or attempted username. Five failures matching either key within 15 minutes lock further login attempts for 15 minutes; a successful login clears matching failure rows. HTTP 429 responses include `Retry-After`.
- Sessions have an eight-hour absolute lifetime and a 30-minute idle timeout. The server refreshes `last_seen_at` on authenticated requests. An expired session returns HTTP 401 with code `session_expired`, clears the cookie, and shows a clear session-expired message in the browser.
- Signed-in users can change their own password from the profile menu's Account details dialog. New passwords must contain at least 12 characters; changing a password invalidates all sessions for that account.
- Existing MySQL databases should apply `database/migrations/009_security_hardening.sql` once. Fresh MySQL installs include these tables and columns from `database/schema.mysql.sql`. SQLite development databases add the idle timestamp column through `init_db()`.
- Optional MySQL login accounts are defined in `database/roles.mysql.sql`. Replace the password placeholders and run it as a MySQL administrator after creating the `casework` schema. `casework_operator` receives `SELECT` only; management receives data DML; the administrator account receives schema privileges. These accounts are intended for separate direct clients or least-privilege demonstrations.
- The current HTTP service uses one `DB_USER`/`DB_PASSWORD` connection from `.env`; it does not switch MySQL accounts for each CASEWORK application user. Application roles are enforced by the API session and role checks. Do not configure the SELECT-only operator account as the API service account because authentication and application writes require database write access.

## MySQL backup and restore

Install the MySQL client tools and configure a credential-protected login path (avoid passwords in command arguments):

```bash
mysql_config_editor set --login-path=casework --host=127.0.0.1 --user=casework_app --password
```

From the repository root, the scripts read `.env` for `DB_NAME`, `DB_HOST`, and `DB_PORT`; `MYSQL_LOGIN_PATH` overrides the login path (defaults to `casework`). They do not use or print `DB_PASSWORD`.

```bash
bash scripts/backup.sh ./backups/casework-2026-10-27.sql
bash scripts/restore.sh ./backups/casework-2026-10-27.sql
```

Backup refuses to overwrite an existing path and writes a single-transaction SQL dump with routines, triggers, events, and binary-safe values, then restricts local file permissions to owner-only where supported. The dump contains the selected schema's objects and rows, but no CREATE DATABASE/USE directive. Restore imports into the existing `DB_NAME`; to test safely, create a disposable schema, set `DB_NAME` to it for restore, and ensure the login path has access to that schema. Restore can drop and replace tables: it prompts for `RESTORE-<DB_NAME>` unless `--confirm` is provided as the second argument. Keep backups encrypted and outside source control. Neither script substitutes for a tested recovery plan; live MySQL backup/restore was not run as part of this project verification.

## Database relationships

- `officers (1) ── (many) cases`: `cases.officer_id` references `officers.id`, set to NULL when a team member is deleted. The API currently blocks deleting an assigned officer until their cases are reassigned.
- `cases (many) ── (many) persons`: `case_persons` stores one row per case, person, and role; deleting a case removes its relationship rows while retaining the person. The legacy `persons.case_id` pointer remains for compatibility and is migrated to role `person_of_interest`.
- `users (1) ── (many) sessions`: deleting a user invalidates their sessions.
- `activity` stores action, record type/reference, short description, actor username, and timestamp; a log row is inserted in the same transaction as each successful mutation.
- `case_view` joins a case to its assigned officer name for lists, dashboard, and exports.
- `officer_workload_view` summarizes total, closed, and open case counts per officer. `repeat_persons_view` lists people linked to more than one distinct case. `public_case_view` exposes basic case details while omitting internal IDs and resolution text.
- The authenticated Analytics page calls `GET /api/analytics`: `RANK()` ranks officers by closed cases, `LAG()` compares monthly case counts, and location hotspots use `GROUP BY ... HAVING COUNT(*) >= 2`. The page provides a separate CSV download for each result. SQLite uses its `strftime` date expression and built-in window functions (SQLite 3.25+); MySQL uses `DATE_FORMAT` and the same window-function logic.
- Evidence can be listed or created at `/api/cases/{reference}/evidence`; individual records support GET, PUT, and DELETE at `/api/evidence/{id}`, with custody transfer at `/api/evidence/{id}/transfer`. Evidence fingerprints are validated as 64-character SHA-256 hex and become immutable after collection. Custody transfers are append-only in both database adapters, and records with transfer history cannot be deleted. The UI stores a path and fingerprint; file upload/storage is not part of this application.
- Court hearings support GET/POST at `/api/cases/{reference}/hearings` and GET/PUT/DELETE at `/api/hearings/{id}`. The dashboard's `upcoming_hearings` payload includes only Scheduled and Adjourned records dated from today through the next 14 days. Hearing writes require Administrator or Management Head access.
- Triggers write case INSERT/UPDATE/DELETE snapshots to `audit_log`; status transitions are recorded in `case_status_history`. The API sets `@app_user` on each MySQL write connection so triggers record the authenticated username. SQLite uses equivalent triggers for local development and tests.
- Closed cases cannot be deleted or reopened through direct SQL or the API. The API returns HTTP 409 with a clear conflict message. Other status changes are allowed.
- MySQL `assign_officer`, `close_case`, `transfer_officer_cases`, and `days_open` routines are created at startup. SQLite uses transactional Python services for the procedures and a compatible `days_open(case_ref)` SQL function. The reports endpoint includes `case_aging`, and the Reports page exports a Days Open CSV.
- Assignment, close, and transfer endpoints require Administrator or Management Head. Operators receive HTTP 403. Close-case requests accept `{ "resolution": "..." }`; transfers accept `{ "to_badge": "..." }`.

## Browser localStorage migration

The API never silently reads, merges, or overwrites the old `casework-*` localStorage keys. To migrate intentionally:

1. Keep a backup of the current browser data.
2. In the old browser app origin, open Developer Tools → Console and export only fictional/demo data:

```javascript
copy(
  JSON.stringify(
    {
      cases: JSON.parse(localStorage.getItem("casework-records") || "[]"),
      persons: JSON.parse(localStorage.getItem("casework-persons") || "[]"),
      officers: JSON.parse(localStorage.getItem("casework-officers") || "[]"),
    },
    null,
    2,
  ),
);
```

3. Save the copied object to a private JSON file (for example `migration.json`) in the repository root. Review it and remove any data you do not intend to migrate.
4. Configure `.env` for the target database and run `python tools/import_browser_export.py migration.json`.
5. The importer validates required fields/references, skips duplicate case references and badge IDs rather than overwriting, commits a valid batch, and prints added/skipped counts. Back up MySQL first. Do not import real sensitive data into this student prototype.
6. Delete the temporary JSON export securely after confirming expected records in the app/database.

The legacy Java app uses the separate `CriminalApplication` MySQL database and FIR/Criminal/Operator/LogIn tables. This web schema is intentionally separate; no automatic schema migration is performed because the legacy schema DDL and exact constraints were not present in the repository.
