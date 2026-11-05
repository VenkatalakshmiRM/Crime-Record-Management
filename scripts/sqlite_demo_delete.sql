-- Run last. Removes the demonstration case from the app.
DELETE FROM cases
WHERE case_ref = 'CASE-2026-020' AND status <> 'Closed';
