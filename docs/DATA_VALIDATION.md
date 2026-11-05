# Data validation rules

The case form offers Investigation, Burglary, Assault, Fraud, Missing person, and Other as common categories. The API intentionally allows additional non-empty category labels for local workflows; define a shared controlled vocabulary before restricting the database. Case opened dates must be valid `YYYY-MM-DD` calendar dates. Scheduled hearing dates must be valid dates and cannot be in the past; completed, adjourned, and cancelled hearings may have historical dates.

Person age is optional and otherwise must be a whole number from 0 through 120. Evidence fingerprints must contain exactly 64 hexadecimal characters. The fingerprint is a recorded value: CASEWORK does not upload or hash the referenced evidence file. Evidence storage paths remain descriptive metadata and must point to the organization's approved evidence store.

Person-to-case links are represented canonically by `case_persons`. `persons.case_id` is retained for compatibility and is synchronized to the first canonical link, or set to NULL when links are removed. A person may be linked to at most 100 cases through the API.

SQLite API writes enforce these rules. SQLite initialization installs additional insert triggers for case category/date, age, evidence fingerprint, and scheduled-hearing date checks. MySQL API writes enforce the same validation; MySQL schema checks constrain age and fingerprint on supported MySQL versions. Existing databases are not automatically rewritten. Review `database/migrations/013_data_validation_preflight.sql` before applying `013_data_validation.sql`.

## Undo

1. Before changing a deployed database, make a normal database backup.
2. For MySQL, undo migration 013 by running `database/migrations/013_data_validation_rollback.sql`.
3. For SQLite, the insert triggers are recreated by application startup. To undo them temporarily, run `DROP TRIGGER IF EXISTS cases_validate_insert; DROP TRIGGER IF EXISTS persons_validate_insert; DROP TRIGGER IF EXISTS evidence_validate_insert; DROP TRIGGER IF EXISTS hearings_validate_insert;` against the configured SQLite database. Reverting the code with Git restores the prior API rules and stops trigger recreation.
4. Revert the code and documentation changes with Git to restore the previous application behavior.

No pre-existing rows are modified by these changes.
