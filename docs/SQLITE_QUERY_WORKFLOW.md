# Run SQLite queries while CASEWORK is open

The CASEWORK SQLite audit triggers use an application-defined function, so direct writes in DB Browser for SQLite may fail. Use the helper below to run a `.sql` file against the same `casework.db`; it registers the audit context, enforces foreign keys, commits successful statements, and rolls back if a statement fails.

Keep CASEWORK open in one browser tab. In PowerShell, from the project folder, run these in order:

```powershell
python scripts/run_sqlite_queries.py scripts/sqlite_demo_insert.sql
python scripts/run_sqlite_queries.py scripts/sqlite_demo_update.sql
python scripts/run_sqlite_queries.py scripts/sqlite_demo_delete.sql
```

After each command, switch back to the CASEWORK tab. It refreshes its records when the tab becomes active. Open **Case records** to see the inserted case, then its edited title/status, and finally confirm it is gone after deletion. The change is also written to the case audit history with actor `sql_demo`.

The example uses `CASE-2026-020`; if that ID is already taken, change it consistently in all three files. The delete example only removes this demo record while it is not closed.
