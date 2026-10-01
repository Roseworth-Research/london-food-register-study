"""
Database helpers for the study.

Two things live here because getting either wrong wastes hours.

Bulk loading
------------
DuckDB is a columnar analytical engine. Inserting rows one at a time through
`executemany` is pathologically slow -- tens of thousands of rows can take
minutes and burn a core doing index maintenance. Loading the same rows as one
columnar batch takes well under a second. Every script in this pipeline builds
a Python list of tuples and hands it to `replace_table`, which does the
columnar load while keeping the explicit CREATE TABLE statement that documents
the schema for a reader.

Single writer
-------------
A DuckDB database file accepts one writing process at a time. The pipeline
scripts are meant to run in sequence, but it is easy to start the next one
while the previous is still committing, and the resulting error is opaque.
`connect` turns it into a clear message.
"""

from __future__ import annotations

import pathlib

import duckdb
import pandas as pd

import config


def connect(
    read_only: bool = False, wait_seconds: int = 0
) -> duckdb.DuckDBPyConnection:
    """Open the study database, with a readable message if it is locked.

    The long-running steps (the per-company API pull, the accounts fetch) hold
    the write lock in short bursts while they flush. `wait_seconds` lets a
    read-only analysis script wait for a gap rather than fail, so results can
    be recomputed while a pull is still running.
    """
    import time

    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            return duckdb.connect(str(config.DB_PATH), read_only=read_only)
        except duckdb.IOException as e:
            if "used by another process" not in str(e):
                raise
            if time.monotonic() >= deadline:
                raise SystemExit(
                    f"{config.DB_PATH} is locked by another process.\n"
                    "The pipeline scripts write to one database and must be run "
                    "in sequence, not in parallel. Wait for the running step to "
                    "finish, or pass wait_seconds to connect()."
                ) from e
            time.sleep(3)


def replace_table(
    con: duckdb.DuckDBPyConnection,
    table: str,
    create_sql: str,
    columns: list[str],
    rows: list[tuple],
) -> int:
    """Drop `table`, create it from `create_sql`, and bulk-load `rows`.

    `create_sql` is the full CREATE TABLE statement. It is kept verbatim rather
    than inferred from the data so that the schema -- including the comments
    that explain what each column means -- is part of the source code a
    reviewer reads, not an artefact of whatever happened to be in the data.
    """
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(create_sql)
    if not rows:
        return 0
    frame = pd.DataFrame(rows, columns=columns)
    con.register("_bulk_load", frame)
    con.execute(f"INSERT INTO {table} SELECT * FROM _bulk_load")
    con.unregister("_bulk_load")
    return len(rows)


def append_flow(
    con: duckdb.DuckDBPyConnection, entries: list[tuple[str, str, int, str]]
) -> None:
    """Record cohort flow counts, creating the table on first use.

    The cohort flow table is the audit trail for the study's sample: every
    company that leaves the cohort leaves through a counted gate, and the
    published flow diagram is drawn from this table rather than from numbers
    typed into a chart by hand.
    """
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS cohort_flow (
            step VARCHAR, stage VARCHAR, n BIGINT, note VARCHAR
        )
        """
    )
    if not entries:
        return
    step = entries[0][0]
    con.execute("DELETE FROM cohort_flow WHERE step = ?", [step])
    frame = pd.DataFrame(entries, columns=["step", "stage", "n", "note"])
    con.register("_flow_load", frame)
    con.execute("INSERT INTO cohort_flow SELECT * FROM _flow_load")
    con.unregister("_flow_load")


def reset_database() -> None:
    """Delete the database and its write-ahead log. Used when re-running from scratch."""
    for suffix in ("", ".wal"):
        p = pathlib.Path(str(config.DB_PATH) + suffix)
        if p.exists():
            p.unlink()
