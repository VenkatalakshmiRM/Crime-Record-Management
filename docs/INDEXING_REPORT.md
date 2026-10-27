# Indexing and performance comparison

## Indexes added

The schema already indexed `cases(status)`, `cases(category)`, `cases(officer_id)`, `persons(case_id)`, and both `case_persons` foreign-key paths. Phase 6 adds `cases(location)`, `persons(name)`, and the composite `cases(status, category, opened_on)` index. It also adds `sessions(user_id)`, which was a missing foreign-key index in the SQLite adapter and improves user-to-session lookups. The MySQL schema already had indexes for the other foreign keys.

The composite case index supports the common filter on both status and category and keeps `opened_on` available for the requested ordering. The individual status and category indexes remain useful for queries filtering by only one of those columns.

## Dataset and procedure

From the project root, seed the database with the default 10,000 fictional cases and 5,000 fictional people:

```powershell
python scripts/seed_large_dataset.py
```

The script prints a unique tag and adds records without deleting existing data. Use a disposable MySQL database for the benchmark. The dataset is synthetic. To choose smaller test sizes, pass `--cases` and `--persons`; pass `--tag` to supply a unique alphanumeric tag.

For a before/after comparison on MySQL 8.0.18 or later:

1. Seed the data, then run the three `EXPLAIN ANALYZE` statements in the **BEFORE INDEX MIGRATION** section of `scripts/explain_compare.sql`. Save the plans and actual times below.
2. Apply `database/migrations/006_performance_indexes.sql` to the existing database. Fresh installs already receive these indexes from `database/schema.mysql.sql`.
3. Rerun the same three statements and save their plans and actual times below. Use the same database and data, and note cache conditions if they differ.

`EXPLAIN ANALYZE` executes the query and reports actual iterator timing and row counts. MySQL was unavailable in this environment, so no plan or timing values are claimed here. Replace the placeholders after running the script against MySQL.

## Results

| Query | Before plan (access type / key / rows) | Before actual time | After plan (access type / key / rows) | After actual time |
|---|---|---:|---|---:|
| Cases by location, ordered by opened date | `[paste EXPLAIN ANALYZE output summary]` | `[___ ms]` | `[paste EXPLAIN ANALYZE output summary]` | `[___ ms]` |
| Persons by name prefix | `[paste EXPLAIN ANALYZE output summary]` | `[___ ms]` | `[paste EXPLAIN ANALYZE output summary]` | `[___ ms]` |
| Cases by status and category | `[paste EXPLAIN ANALYZE output summary]` | `[___ ms]` | `[paste EXPLAIN ANALYZE output summary]` | `[___ ms]` |

Expected index candidates after the migration are `idx_cases_location`, `idx_persons_name`, and `idx_cases_status_category_opened`; the optimizer may choose another plan depending on table statistics and selectivity. Record the observed keys instead of assuming these candidates were selected.

## Trade-offs

The added indexes consume disk and increase the work required for inserts and changes to indexed fields. This is a deliberate trade-off for the filter and sort queries above. Compare query plans and actual timing on the same data before deciding whether an index is useful for a particular deployment.
