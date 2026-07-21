"""
Shared fixture for tests that exercise real Postgres objects (views,
constraints) rather than pure Python logic. Every test runs inside a
transaction that is rolled back on teardown, so fixture rows never persist.

Requires PG_HOST/PG_PORT/PG_DATABASE/PG_USER/PG_PASSWORD in the environment
(see .env.example) -- PG_PASSWORD is a short-lived Entra ID access token.
"""
import os

import psycopg2
import pytest
from dotenv import load_dotenv

load_dotenv()


@pytest.fixture
def pg_conn():
    conn = psycopg2.connect(
        host=os.environ["PG_HOST"],
        port=os.environ["PG_PORT"],
        dbname=os.environ["PG_DATABASE"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        sslmode="require",
    )
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
