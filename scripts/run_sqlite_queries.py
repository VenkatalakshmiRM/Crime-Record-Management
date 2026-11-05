#!/usr/bin/env python3
"""Run SQL files against CASEWORK's SQLite database with its audit context enabled."""
from __future__ import annotations
import argparse
import sqlite3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend.api as api  # noqa: E402

def statements_from(source: str):
    buffer = ""
    for char in source:
        buffer += char
        if char == ";" and sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                yield statement
            buffer = ""
    if buffer.strip():
        if not sqlite3.complete_statement(buffer + ";"):
            raise ValueError("SQL file ends with an incomplete statement.")
        yield buffer.strip()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sql_file", type=Path, help="A .sql file containing one or more SQLite statements")
    parser.add_argument("--actor", default="sql_demo", help="Actor recorded in audit history (default: sql_demo)")
    args = parser.parse_args()
    if api.os.environ.get("CASEWORK_DB", "sqlite").lower() != "sqlite":
        parser.error("This helper runs against SQLite; set CASEWORK_DB=sqlite first.")
    source = args.sql_file.read_text(encoding="utf-8")
    conn = api.connect()
    try:
        api.set_db_actor(conn, {"username": args.actor})
        for statement in statements_from(source):
            cursor = conn.execute(statement)
            if cursor.description:
                rows = cursor.fetchall()
                headers = [column[0] for column in cursor.description]
                print("\t".join(headers))
                for row in rows:
                    print("\t".join(str(value if value is not None else "") for value in row))
            else:
                print(f"{cursor.rowcount} row(s) affected")
        conn.commit()
        print("SQL committed successfully.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()
