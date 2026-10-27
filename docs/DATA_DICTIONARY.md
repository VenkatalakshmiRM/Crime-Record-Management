# CASEWORK data dictionary

This dictionary follows the MySQL 8 target definitions in `database/schema.mysql.sql`. SQLite uses adapter-specific integer and text equivalents. `PK` = primary key, `FK` = foreign key, `UQ` = unique, `NN` = NOT NULL. InnoDB is used for all base tables.

## Base tables

### `users`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `username` | VARCHAR(80) | NN, UQ; login identifier |
| `password_hash` | VARCHAR(200) | NN; PBKDF2-SHA256 encoded hash, never plaintext |
| `name` | VARCHAR(160) | NN; display name |
| `role` | ENUM('Administrator','Management Head','Operator') | NN; application authorization role |
| `active` | BOOLEAN | NN, default TRUE; disabled accounts cannot authenticate |
| `created_at` | VARCHAR(40) | NN; ISO-8601 timestamp |

### `officers`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `name` | VARCHAR(160) | NN |
| `role` | VARCHAR(120) | NN; staff designation |
| `badge` | VARCHAR(80) | NN, UQ |
| `created_at` | VARCHAR(40) | NN; ISO-8601 timestamp |
| `updated_at` | VARCHAR(40) | NN; ISO-8601 timestamp |

### `cases`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `case_ref` | VARCHAR(80) | NN, UQ; stable public reference |
| `title` | VARCHAR(240) | NN |
| `category` | VARCHAR(100) | NN |
| `status` | ENUM('Active','Under review','Pending','Closed') | NN; checked by case lifecycle triggers |
| `officer_id` | BIGINT UNSIGNED | FK → `officers.id`, nullable, ON DELETE SET NULL |
| `opened_on` | DATE | Nullable |
| `location` | VARCHAR(240) | NN, default empty string |
| `resolution` | TEXT | Nullable; sensitive internal resolution details |
| `created_at` | VARCHAR(40) | NN; ISO-8601 timestamp |
| `updated_at` | VARCHAR(40) | NN; ISO-8601 timestamp |

Indexes: `case_ref` unique; `idx_cases_status`, `idx_cases_status_category_opened`, `idx_cases_category`, `idx_cases_location`, `idx_cases_officer`, `idx_cases_opened`.

### `persons`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `name` | VARCHAR(160) | NN |
| `case_id` | BIGINT UNSIGNED | Nullable legacy FK → `cases.id`, ON DELETE SET NULL; canonical links belong in `case_persons` |
| `age` | SMALLINT UNSIGNED | Nullable; application validates 0–120 |
| `status` | ENUM('Under investigation','In custody','Released on bail','Wanted','Unknown') | NN |
| `charge` | VARCHAR(240) | NN |
| `created_at` | VARCHAR(40) | NN; ISO-8601 timestamp |
| `updated_at` | VARCHAR(40) | NN; ISO-8601 timestamp |

Indexes: `idx_persons_case`, `idx_persons_name`, `idx_persons_status`.

### `case_persons`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `case_reference` | VARCHAR(80) | PK part, NN, FK → `cases.case_ref`, ON DELETE CASCADE |
| `person_id` | BIGINT UNSIGNED | PK part, NN, FK → `persons.id`, ON DELETE CASCADE |
| `role` | ENUM('suspect','witness','victim','person_of_interest') | PK part, NN; relationship role |
| `added_at` | VARCHAR(40) | NN; link timestamp |

Composite PK: (`case_reference`,`person_id`,`role`); secondary index `idx_case_persons_person(person_id,case_reference)`.

### `evidence`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `case_reference` | VARCHAR(80) | NN, FK → `cases.case_ref`, ON DELETE RESTRICT |
| `description` | TEXT | NN |
| `type` | VARCHAR(80) | NN; quoted SQL identifier |
| `hash` | CHAR(64) | NN; SHA-256 hex fingerprint, immutable after collection in the API |
| `storage_path` | VARCHAR(500) | NN; external evidence file path, not the file itself |
| `collected_by` | BIGINT UNSIGNED | NN, FK → `officers.id`, ON DELETE RESTRICT |
| `collected_at` | VARCHAR(40) | NN; collection timestamp |

Indexes: `idx_evidence_case(case_reference,id)`, `idx_evidence_collector(collected_by)`.

### `custody_log`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `evidence_id` | BIGINT UNSIGNED | NN, FK → `evidence.id`, ON DELETE RESTRICT |
| `from_officer` | BIGINT UNSIGNED | Nullable FK → `officers.id`, ON DELETE RESTRICT; NULL for initial collection event |
| `to_officer` | BIGINT UNSIGNED | NN, FK → `officers.id`, ON DELETE RESTRICT |
| `purpose` | VARCHAR(500) | NN; transfer reason or collection note |
| `transferred_at` | VARCHAR(40) | NN; event timestamp |

Append-only triggers block UPDATE and DELETE. Indexes: `idx_custody_evidence(evidence_id,id)`, `idx_custody_from_officer(from_officer)`, `idx_custody_to_officer(to_officer)`.

### `hearings`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `case_reference` | VARCHAR(80) | NN, FK → `cases.case_ref`, ON DELETE RESTRICT |
| `court` | VARCHAR(240) | NN |
| `hearing_date` | DATE | NN |
| `status` | ENUM('Scheduled','Completed','Adjourned','Cancelled') | NN |
| `outcome` | TEXT | Nullable |
| `notes` | TEXT | Nullable |

Indexes: `idx_hearings_case(case_reference,hearing_date)`, `idx_hearings_date_status(hearing_date,status)`.

### `activity`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `action` | VARCHAR(60) | NN; mutation/action name |
| `record_type` | VARCHAR(60) | NN; case, person, officer, user, etc. |
| `record_ref` | VARCHAR(100) | NN; human-readable record identifier |
| `description` | VARCHAR(300) | NN; short event summary |
| `actor` | VARCHAR(80) | Nullable username; deliberately not an FK so historical entries persist |
| `created_at` | VARCHAR(40) | NN; ISO-8601 timestamp |

Indexes: `idx_activity_created(created_at)`, `idx_activity_record(record_type,record_ref)`.

### `sessions`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `token_hash` | CHAR(64) | PK; SHA-256 of random HTTP session token |
| `user_id` | BIGINT UNSIGNED | NN, FK → `users.id`, ON DELETE CASCADE |
| `expires_at` | VARCHAR(40) | NN; eight-hour absolute expiry |
| `last_seen_at` | VARCHAR(40) | NN; refreshed on authenticated requests; 30-minute idle expiry |

Indexes: `idx_sessions_expiry(expires_at)`, `idx_sessions_user_id(user_id)`.

### `login_attempts`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `username_key` | CHAR(64) | NN; SHA-256 of normalized username; raw username not stored |
| `ip_key` | CHAR(64) | NN; SHA-256 of remote IP; raw IP not stored |
| `attempted_at` | VARCHAR(40) | NN; attempt timestamp |
| `succeeded` | BOOLEAN | NN, default FALSE |
| `locked_until` | VARCHAR(40) | Nullable; lock expiry set on the fifth failure |

Indexes: `idx_login_attempts_username_time(username_key,attempted_at)`, `idx_login_attempts_ip_time(ip_key,attempted_at)`. Five failed attempts lock a matching account or IP for 15 minutes.

### `audit_log`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `table_name` | VARCHAR(64) | NN; source table name |
| `record_key` | VARCHAR(80) | NN; case reference for case audit rows |
| `action` | VARCHAR(10) | NN; INSERT, UPDATE, or DELETE |
| `old_values` | JSON | Nullable; prior case data for update/delete |
| `new_values` | JSON | Nullable; resulting case data for insert/update |
| `changed_by` | VARCHAR(80) | Nullable actor username from `@app_user` |
| `changed_at` | VARCHAR(40) | NN; audit timestamp |

Index: `idx_audit_record(table_name,record_key,id)`.

### `case_status_history`

| Column | MySQL type | Constraints / meaning |
|---|---|---|
| `id` | BIGINT UNSIGNED | PK, AUTO_INCREMENT |
| `case_reference` | VARCHAR(80) | NN; case reference retained in history |
| `old_status` | VARCHAR(40) | Nullable prior status |
| `new_status` | VARCHAR(40) | Nullable resulting status |
| `changed_by` | VARCHAR(80) | Nullable actor username |
| `changed_at` | VARCHAR(40) | NN; transition timestamp |

Index: `idx_case_status_history_ref(case_reference,id)`.

## Views

| View | Output columns | Definition / use |
|---|---|---|
| `case_view` | `id`, `case_ref`, `title`, `category`, `status`, `officer_id`, `officer_name`, `opened_on`, `location`, `resolution`, `created_at`, `updated_at` | Cases LEFT JOIN officers by officer ID |
| `officer_workload_view` | `officer_id`, `officer_name`, `role`, `badge`, `total_cases`, `closed_cases`, `open_cases` | Officer assignment counts aggregated from cases |
| `repeat_persons_view` | `person_id`, `name`, `status`, `charge`, `case_count` | Person/case links grouped; only people linked to >1 distinct case |
| `public_case_view` | `case_ref`, `title`, `category`, `status`, `opened_on`, `location` | Restricted projection omitting internal IDs and resolution |

## Triggers and stored routines

The fresh MySQL schema defines `cases_audit_insert`, `cases_audit_update`, and `cases_audit_delete`; `cases_status_history_update`; `cases_block_closed_delete`; and `cases_reject_reopen`. It also defines `custody_log_no_update` and `custody_log_no_delete`. The procedures are `assign_officer(case_ref)`, `close_case(case_ref,resolution,user)`, and `transfer_officer_cases(from_badge,to_badge)`. The function is `days_open(case_ref) RETURNS INT`. These routines add no columns beyond those listed above.

Constraint and index names are listed by their owning table. The exact authoritative definitions, including engine, default values, foreign-key actions, and trigger bodies, are in `database/schema.mysql.sql`.
