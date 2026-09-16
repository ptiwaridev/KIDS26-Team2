"""Creates the read-only SQL login the app should connect with — never point
the app at the admin credentials used for provisioning/ingestion.

Uses AZURE_SQL_SERVER/DATABASE/USERNAME/PASSWORD from .env as the admin
connection to run this (temporarily swap .env to admin creds if it's
currently set to app_readonly — see .env's comment). Idempotent: safe to
re-run, skips creation if the login/user already exists.

Usage:
    python scripts/create_readonly_login.py                # generates a password
    python scripts/create_readonly_login.py --password '...'
"""
import argparse
import secrets
import string
import urllib.parse

from sqlalchemy import create_engine, text

from db import get_engine


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%^*_-"
    return "Ro" + "".join(secrets.choice(alphabet) for _ in range(16))


def engine_for_database(admin_engine_url_parts: dict, database: str):
    conn_str = (
        f"Driver={{ODBC Driver 18 for SQL Server}};Server=tcp:{admin_engine_url_parts['server']},1433;"
        f"Database={database};Uid={admin_engine_url_parts['user']};Pwd={admin_engine_url_parts['password']};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=90;"
    )
    odbc_str = urllib.parse.quote_plus(conn_str)
    return create_engine(f"mssql+pyodbc:///?odbc_connect={odbc_str}")


def main():
    import os

    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--password", default=None, help="Defaults to a generated password")
    parser.add_argument("--login-name", default="app_readonly")
    args = parser.parse_args()

    password = args.password or generate_password()
    login_name = args.login_name

    server = os.environ["AZURE_SQL_SERVER"]
    target_db = os.environ["AZURE_SQL_DATABASE"]
    admin_parts = {"server": server, "user": os.environ["AZURE_SQL_USERNAME"], "password": os.environ["AZURE_SQL_PASSWORD"]}

    master_engine = engine_for_database(admin_parts, "master")
    with master_engine.begin() as conn:
        exists = conn.execute(text("SELECT COUNT(*) FROM sys.sql_logins WHERE name = :n"), {"n": login_name}).scalar()
        if exists:
            print(f"Login {login_name} already exists on the server — leaving its password as-is.")
        else:
            conn.execute(text(f"CREATE LOGIN {login_name} WITH PASSWORD = '{password}'"))
            print(f"Created server login {login_name}")

    db_engine = engine_for_database(admin_parts, target_db)
    with db_engine.begin() as conn:
        exists = conn.execute(text("SELECT COUNT(*) FROM sys.database_principals WHERE name = :n"),
                               {"n": login_name}).scalar()
        if exists:
            print(f"Database user {login_name} already exists on {target_db}.")
        else:
            conn.execute(text(f"CREATE USER {login_name} FROM LOGIN {login_name}"))
            conn.execute(text(f"ALTER ROLE db_datareader ADD MEMBER {login_name}"))
            print(f"Created database user {login_name} on {target_db} with db_datareader")

    print()
    print("Put these in .env (only if the login was newly created above — if it")
    print("already existed, use its actual password, not the one printed here):")
    print(f"AZURE_SQL_USERNAME={login_name}")
    print(f"AZURE_SQL_PASSWORD={password}")


if __name__ == "__main__":
    main()
