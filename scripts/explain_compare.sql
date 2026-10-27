-- EXPLAIN comparison for MySQL 8.0.18+; run the BEFORE section first, then apply
-- database/migrations/006_performance_indexes.sql, then run AFTER. Both use the
-- same representative predicates. Seed with scripts/seed_large_dataset.py first.
-- Capture each EXPLAIN ANALYZE result and elapsed time in docs/INDEXING_REPORT.md.

-- BEFORE INDEX MIGRATION
EXPLAIN ANALYZE
SELECT id,case_ref,title,opened_on
FROM cases
WHERE location='Fictional Precinct 01'
ORDER BY opened_on DESC
LIMIT 50;

EXPLAIN ANALYZE
SELECT id,name,status,charge
FROM persons
WHERE name LIKE 'PerfSubject-01-%'
ORDER BY name
LIMIT 100;

EXPLAIN ANALYZE
SELECT id,case_ref,title,opened_on
FROM cases
WHERE status='Active' AND category='Burglary'
ORDER BY opened_on DESC
LIMIT 100;

-- AFTER INDEX MIGRATION: these queries are intentionally repeated so the
-- second result set can be compared directly to the baseline output above.
EXPLAIN ANALYZE
SELECT id,case_ref,title,opened_on
FROM cases
WHERE location='Fictional Precinct 01'
ORDER BY opened_on DESC
LIMIT 50;

EXPLAIN ANALYZE
SELECT id,name,status,charge
FROM persons
WHERE name LIKE 'PerfSubject-01-%'
ORDER BY name
LIMIT 100;

EXPLAIN ANALYZE
SELECT id,case_ref,title,opened_on
FROM cases
WHERE status='Active' AND category='Burglary'
ORDER BY opened_on DESC
LIMIT 100;
