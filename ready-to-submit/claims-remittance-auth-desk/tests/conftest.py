"""Shared live-database fixtures for the claims remittance verifier."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

APP = Path("/app/claims")
CLI = APP / "bin" / "claimsctl"


def cli_environment() -> dict[str, str]:
    """Return connection defaults while honoring Harbor-provided overrides."""
    environment = os.environ.copy()
    environment.setdefault("CLAIMS_DB", "claims@127.0.0.1:5432")
    environment.setdefault("CLAIMS_DB_USER", "claims_app")
    environment.setdefault("CLAIMS_DB_PASSWORD", "claims_local")
    return environment


def connection() -> psycopg.Connection:
    """Open a verifier connection to the task's PostgreSQL sidecar."""
    return psycopg.connect(
        host=os.environ.get("CLAIMS_DB_HOST", "127.0.0.1"),
        dbname="claims",
        user="claims_app",
        password="claims_local",
        autocommit=True,
    )


def run_cli(*args: object, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    """Run one public terminal command with captured line-oriented output."""
    return subprocess.run(
        [str(CLI), *(str(arg) for arg in args)],
        cwd=APP,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=cli_environment(),
    )


def scalar(query: str, params: tuple[object, ...] = ()) -> object:
    """Return the first column from a single-row database query."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()
    assert row is not None
    return row[0]


@pytest.fixture(scope="session", autouse=True)
def built_application() -> Iterator[None]:
    """Wait for PostgreSQL and rebuild the submitted COBOL sources once."""
    deadline = time.monotonic() + 90
    while True:
        try:
            with connection() as conn:
                conn.execute("SELECT 1")
            break
        except psycopg.OperationalError:
            if time.monotonic() >= deadline:
                pytest.fail("PostgreSQL sidecar did not become ready")
            time.sleep(1)

    with connection() as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    database_environment = os.environ.copy()
    database_environment.setdefault(
        "PGHOST", os.environ.get("CLAIMS_DB_HOST", "127.0.0.1")
    )
    database_environment.setdefault("PGDATABASE", "claims")
    database_environment.setdefault("PGUSER", "claims_app")
    database_environment.setdefault("PGPASSWORD", "claims_local")
    migration = subprocess.run(
        [
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            str(APP / "db" / "schema.sql"),
        ],
        cwd=APP,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
        env=database_environment,
    )
    if migration.returncode != 0:
        pytest.fail(
            f"database migration failed:\n{migration.stdout}\n{migration.stderr}"
        )

    result = subprocess.run(
        [str(APP / "bin" / "build-claims")],
        cwd=APP,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"COBOL build failed:\n{result.stdout}\n{result.stderr}")
    yield


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    """Give every test an independent operational database state."""
    with connection() as conn:
        conn.execute(
            "TRUNCATE audit_event, request_record, remittance, claim"
        )
        conn.execute("UPDATE audit_counter SET next_value = 1")
    yield
