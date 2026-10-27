# CASEWORK database ER diagram

The diagram describes the MySQL target schema in `database/schema.mysql.sql`. It shows physical foreign-key relationships. The legacy nullable `persons.case_id` link is retained for older clients; new person-to-case links use `case_persons`.

```mermaid
erDiagram
    USERS {
        BIGINT id PK
        VARCHAR username UK
        VARCHAR password_hash
        VARCHAR name
        ENUM role
        BOOLEAN active
        VARCHAR created_at
    }
    SESSIONS {
        CHAR token_hash PK
        BIGINT user_id FK
        VARCHAR expires_at
        VARCHAR last_seen_at
    }
    LOGIN_ATTEMPTS {
        BIGINT id PK
        CHAR username_key
        CHAR ip_key
        VARCHAR attempted_at
        BOOLEAN succeeded
        VARCHAR locked_until
    }
    OFFICERS {
        BIGINT id PK
        VARCHAR name
        VARCHAR role
        VARCHAR badge UK
        VARCHAR created_at
        VARCHAR updated_at
    }
    CASES {
        BIGINT id PK
        VARCHAR case_ref UK
        VARCHAR title
        VARCHAR category
        ENUM status
        DATE opened_on
        VARCHAR location
        TEXT resolution
        VARCHAR created_at
        VARCHAR updated_at
    }
    PERSONS {
        BIGINT id PK
        VARCHAR name
        BIGINT case_id FK "legacy nullable link"
        SMALLINT age
        ENUM status
        VARCHAR charge
        VARCHAR created_at
        VARCHAR updated_at
    }
    CASE_PERSONS {
        VARCHAR case_reference PK, FK
        BIGINT person_id PK, FK
        ENUM role PK
        VARCHAR added_at
    }
    EVIDENCE {
        BIGINT id PK
        VARCHAR case_reference FK
        TEXT description
        VARCHAR type
        CHAR hash
        VARCHAR storage_path
        BIGINT collected_by FK
        VARCHAR collected_at
    }
    CUSTODY_LOG {
        BIGINT id PK
        BIGINT evidence_id FK
        BIGINT from_officer FK
        BIGINT to_officer FK
        VARCHAR purpose
        VARCHAR transferred_at
    }
    HEARINGS {
        BIGINT id PK
        VARCHAR case_reference FK
        VARCHAR court
        DATE hearing_date
        ENUM status
        TEXT outcome
        TEXT notes
    }
    ACTIVITY {
        BIGINT id PK
        VARCHAR action
        VARCHAR record_type
        VARCHAR record_ref
        VARCHAR description
        VARCHAR actor
        VARCHAR created_at
    }
    AUDIT_LOG {
        BIGINT id PK
        VARCHAR table_name
        VARCHAR record_key
        VARCHAR action
        JSON old_values
        JSON new_values
        VARCHAR changed_by
        VARCHAR changed_at
    }
    CASE_STATUS_HISTORY {
        BIGINT id PK
        VARCHAR case_reference
        VARCHAR old_status
        VARCHAR new_status
        VARCHAR changed_by
        VARCHAR changed_at
    }

    USERS ||--o{ SESSIONS : "owns"
    OFFICERS o|--o{ CASES : "assigned to"
    CASES o|--o{ PERSONS : "legacy case_id"
    CASES ||--o{ CASE_PERSONS : "has links"
    PERSONS ||--o{ CASE_PERSONS : "has links"
    CASES ||--o{ EVIDENCE : "documents"
    OFFICERS ||--o{ EVIDENCE : "collected by"
    EVIDENCE ||--o{ CUSTODY_LOG : "custody events"
    OFFICERS o|--o{ CUSTODY_LOG : "transfer from"
    OFFICERS ||--o{ CUSTODY_LOG : "transfer to"
    CASES ||--o{ HEARINGS : "scheduled for"
```

`case_persons` is the normalized many-to-many link and allows one person to have several roles or case links. `persons.case_id` is a compatibility field and is not the canonical relationship. `activity.actor`, `audit_log`, and `case_status_history` keep audit references without foreign keys so history can remain available independently of a user or case row. `login_attempts` stores SHA-256 identifiers for usernames and IP addresses, not the raw values.

## Application role hierarchy

The `users.role` column contains the application role; the hierarchy is enforced by API authorization and the UI:

1. **Management Head** — highest privilege; can manage user accounts and all case, person, team, evidence, and hearing operations.
2. **Administrator** — can manage cases, persons of interest, team members, evidence, and hearings, but cannot manage user accounts.
3. **Operator** — read-only access to the application records; cannot change cases, persons, team members, or user accounts.

The reporting views are not repeated as entities because they do not store rows: `case_view`, `officer_workload_view`, `repeat_persons_view`, and `public_case_view` are documented in [DATA_DICTIONARY.md](DATA_DICTIONARY.md).
