"""DuckDB connection and schema."""

from __future__ import annotations

from pathlib import Path

import duckdb

from value_invest.config import ROOT, settings

SCHEMA_SQL = ROOT / "data" / "schema.sql"


def connect(path: Path | None = None, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    p = path or settings().duckdb_path
    p.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(p), read_only=read_only)
    if not read_only:
        init_schema(con)
    return con


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SCHEMA_SQL.read_text())


def table_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    rows = con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'vi' ORDER BY 1"
    ).fetchall()
    return {t: con.execute(f"SELECT count(*) FROM vi.{t}").fetchone()[0] for (t,) in rows}
