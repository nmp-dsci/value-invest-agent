"""The SQL viewer's executor: one read-only SELECT at a time over the vi schema.

Modelled on data-qa-agent's `run_select`: the connection is read-only (DuckDB
refuses writes at the engine level), the statement is validated as a single
SELECT/WITH before it runs, results are capped, and long queries are
interrupted. There is no user model here — it is a local dev viewer."""

from __future__ import annotations

import threading
import time
from typing import Any

import duckdb

MAX_ROWS = 1000
TIMEOUT_S = 20.0
FORBIDDEN = ("attach", "copy", "export", "import", "install", "load", "pragma", "set ", "call ")


class SqlError(ValueError):
    pass


def validate_select(sql: str) -> str:
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise SqlError("empty query")
    try:
        statements = duckdb.extract_statements(text)
    except duckdb.Error as e:
        raise SqlError(f"parse error: {e}") from e
    if len(statements) != 1:
        raise SqlError("one statement at a time")
    head = text.lower().lstrip("(")
    if not (head.startswith("select") or head.startswith("with") or head.startswith("from")):
        raise SqlError("only SELECT / WITH / FROM queries are allowed")
    low = f" {text.lower()} "
    for word in FORBIDDEN:
        if f" {word}" in low:
            raise SqlError(f"'{word.strip()}' is not allowed in the viewer")
    return text


def run_select(
    con: duckdb.DuckDBPyConnection, sql: str, max_rows: int = MAX_ROWS
) -> dict[str, Any]:
    text = validate_select(sql)
    wrapped = f"SELECT * FROM ({text}) AS _q LIMIT {int(max_rows) + 1}"
    timer = threading.Timer(TIMEOUT_S, con.interrupt)
    started = time.perf_counter()
    timer.start()
    try:
        cur = con.execute(wrapped)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    except duckdb.InterruptException as e:
        raise SqlError(f"query interrupted after {TIMEOUT_S:.0f}s") from e
    except duckdb.Error as e:
        raise SqlError(str(e).splitlines()[0][:400]) from e
    finally:
        timer.cancel()
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    return {
        "columns": cols,
        "rows": [[_json_safe(v) for v in r] for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "sql": text,
    }


def _json_safe(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def catalog(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    tables = []
    for name, kind in con.execute(
        "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = 'vi' ORDER BY 1"
    ).fetchall():
        cols = con.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'vi' AND table_name = ? ORDER BY ordinal_position",
            [name],
        ).fetchall()
        n = None
        if kind == "BASE TABLE":
            n = con.execute(f"SELECT count(*) FROM vi.{name}").fetchone()[0]
        tables.append(
            {
                "name": f"vi.{name}",
                "kind": "view" if kind == "VIEW" else "table",
                "rows": n,
                "columns": [{"name": c, "type": t} for c, t in cols],
            }
        )
    macros = [
        {
            "name": "vi.prices_as_of(ticker, t0)",
            "kind": "macro",
            "doc": "daily prices for a ticker dated ≤ t0",
        },
        {
            "name": "vi.statements_as_of(ticker, t0)",
            "kind": "macro",
            "doc": "annual line items whose available_from ≤ t0 (EDGAR: real filing date; yfinance: period_end + 90 d)",
        },
    ]
    return {"tables": tables, "macros": macros, "examples": EXAMPLES}


EXAMPLES = [
    {
        "title": "The sampled videos",
        "sql": "SELECT published_at, primary_ticker, title, year_bucket, sample_rank, transcript_status\nFROM vi.videos WHERE in_sample ORDER BY published_at",
    },
    {
        "title": "Statements an agent may see for one video",
        "sql": "SELECT period_end, kind, line_item, value, available_from, source\nFROM vi.statements_as_of('AAPL', DATE '2022-09-20')\nWHERE line_item IN ('Total Revenue', 'Net Income', 'Total Assets', 'Free Cash Flow')\nORDER BY period_end DESC, kind",
    },
    {
        "title": "Revenue history per fiscal year (EDGAR wins where both exist)",
        "sql": "SELECT year(period_end) AS fy, max(value) FILTER (WHERE source='edgar') AS edgar, max(value) FILTER (WHERE source='yfinance') AS yfinance\nFROM vi.statements WHERE ticker = 'AAPL' AND line_item = 'Total Revenue'\nGROUP BY 1 ORDER BY 1",
    },
    {
        "title": "Complete fiscal years visible at each video's T0",
        "sql": "SELECT v.published_at AS t0, v.primary_ticker, count(*) FILTER (WHERE f.complete AND f.available_from <= v.published_at) AS fys_visible\nFROM vi.videos v LEFT JOIN vi.fiscal_years f ON f.ticker = v.primary_ticker\nWHERE v.in_sample GROUP BY 1, 2 ORDER BY 1",
    },
    {
        "title": "Forward return 12 months after each video",
        "sql": "WITH p0 AS (\n  SELECT v.video_id, v.primary_ticker AS ticker, v.published_at AS t0,\n         (SELECT close FROM vi.prices p WHERE p.ticker = v.primary_ticker AND p.date <= v.published_at ORDER BY date DESC LIMIT 1) AS c0,\n         (SELECT close FROM vi.prices p WHERE p.ticker = v.primary_ticker AND p.date >= v.published_at + INTERVAL 365 DAY ORDER BY date LIMIT 1) AS c12\n  FROM vi.videos v WHERE v.in_sample)\nSELECT t0, ticker, round(c0, 2) AS close_t0, round(c12, 2) AS close_12m, round(100 * (c12 / c0 - 1), 1) AS ret_12m_pct\nFROM p0 WHERE c12 IS NOT NULL ORDER BY t0",
    },
    {
        "title": "Classifier labels by kind and year",
        "sql": "SELECT year_bucket, kind, count(*) AS n, round(avg(l.confidence), 2) AS avg_conf\nFROM vi.videos v JOIN vi.title_labels l USING (video_id)\nWHERE year_bucket IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 3 DESC",
    },
    {
        "title": "Which line items EDGAR provides",
        "sql": "SELECT kind, line_item, count(DISTINCT ticker) AS tickers, count(*) AS rows\nFROM vi.statements WHERE source = 'edgar' GROUP BY 1, 2 ORDER BY 1, 3 DESC",
    },
]
