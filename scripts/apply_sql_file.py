"""Applies a plain T-SQL script (no sqlcmd GO batches or $(var) substitution)
to Azure SQL via pyodbc — used instead of sqlcmd, which isn't installed in
the app container. Only handles files with semicolon-terminated statements,
which is all sql/schema.sql needs.

Usage:
    python scripts/apply_sql_file.py sql/schema.sql
"""
import argparse
from pathlib import Path

from sqlalchemy import text

from db import get_engine


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sql_file")
    args = parser.parse_args()

    sql = Path(args.sql_file).read_text()
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    engine = get_engine()
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))

    print(f"Applied {len(statements)} statement(s) from {args.sql_file}")


if __name__ == "__main__":
    main()
