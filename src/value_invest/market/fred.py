"""FRED daily treasury yields → ``vi.rates`` (D11 · X1).

``https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10`` needs no key.
DGS10 (10-year) and DGS3MO (3-month) are the "risk-free" he compares dividend
yields with ("you can lend to the US government at 4 %"). Cached under
``.vi/fred/`` for a week."""

from __future__ import annotations

import csv
import io
import time
from datetime import date
from typing import Any

import duckdb
import httpx

from value_invest.config import settings

SERIES = ("DGS10", "DGS3MO")
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"


def fetch_series(series: str, max_age_days: int = 7) -> list[tuple[date, float]]:
    cache = settings().cache_dir / "fred" / f"{series}.csv"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not (cache.exists() and (time.time() - cache.stat().st_mtime) < max_age_days * 86400):
        r = httpx.get(URL.format(series=series), timeout=60, follow_redirects=True)
        r.raise_for_status()
        cache.write_text(r.text)
    rows: list[tuple[date, float]] = []
    for rec in csv.DictReader(io.StringIO(cache.read_text())):
        raw = rec.get(series) or rec.get("VALUE") or ""
        if raw in ("", "."):
            continue
        d = rec.get("observation_date") or rec.get("DATE") or ""
        rows.append((date.fromisoformat(d), float(raw) / 100.0))  # percent → fraction
    return rows


def load_rates(con: duckdb.DuckDBPyConnection, series: tuple[str, ...] = SERIES) -> dict[str, Any]:
    out = {}
    for s in series:
        rows = fetch_series(s)
        con.executemany(
            "INSERT OR REPLACE INTO vi.rates (series, date, value) VALUES (?, ?, ?)",
            [(s, d, v) for d, v in rows],
        )
        out[s] = {
            "rows": len(rows),
            "first": str(rows[0][0]) if rows else None,
            "last": str(rows[-1][0]) if rows else None,
        }
    return out


def rate_as_of(con: duckdb.DuckDBPyConnection, series: str, t0: date) -> float | None:
    r = con.execute(
        "SELECT value FROM vi.rates WHERE series = ? AND date <= ? ORDER BY date DESC LIMIT 1",
        [series, t0],
    ).fetchone()
    return float(r[0]) if r else None
