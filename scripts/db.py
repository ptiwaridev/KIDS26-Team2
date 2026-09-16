"""Shared Azure SQL connection factory — used by ingestion scripts and (later)
the Text-to-SQL agent so the connection logic lives in one place.
"""
import os
import urllib.parse

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

load_dotenv()


def get_engine() -> Engine:
    conn_string = os.getenv("AZURE_SQL_CONNECTION_STRING")
    if not conn_string:
        server = os.environ["AZURE_SQL_SERVER"]
        database = os.environ["AZURE_SQL_DATABASE"]
        username = os.environ["AZURE_SQL_USERNAME"]
        password = os.environ["AZURE_SQL_PASSWORD"]
        conn_string = (
            f"Driver={{ODBC Driver 18 for SQL Server}};Server=tcp:{server},1433;"
            f"Database={database};Uid={username};Pwd={password};"
            # Serverless-tier databases auto-pause and can take up to ~60s to
            # resume on a cold connection — 30s was cutting it close.
            "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=90;"
        )
    odbc_str = urllib.parse.quote_plus(conn_string)
    return create_engine(f"mssql+pyodbc:///?odbc_connect={odbc_str}", fast_executemany=True)
