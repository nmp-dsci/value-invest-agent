"""S2 — load Yahoo prices + annual statements for every sampled ticker (and
each ticker's benchmark) into DuckDB."""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from value_invest.market import yahoo


def _upsert_prices(con: duckdb.DuckDBPyConnection, df) -> int:
    if df.empty:
        return 0
    con.register("_p", df)
    con.execute("INSERT OR REPLACE INTO vi.prices SELECT ticker, date, open, high, low, close, adj_close, CAST(volume AS BIGINT) FROM _p")
    con.unregister("_p")
    return len(df)


def _upsert_statements(con: duckdb.DuckDBPyConnection, df) -> int:
    if df.empty:
        return 0
    con.register("_s", df)
    con.execute("INSERT OR REPLACE INTO vi.statements SELECT ticker, period_end, kind, freq, line_item, value, filed_at, available_from, source FROM _s")
    con.unregister("_s")
    return len(df)


def load_market(con: duckdb.DuckDBPyConnection, only_missing: bool = True, tickers: list[str] | None = None) -> dict:
    sampled = tickers or [
        r[0] for r in con.execute("SELECT DISTINCT primary_ticker FROM vi.videos WHERE in_sample AND primary_ticker IS NOT NULL ORDER BY 1").fetchall()
    ]
    have = {r[0] for r in con.execute("SELECT ticker FROM vi.tickers WHERE yahoo_ok").fetchall()} if only_missing else set()
    benches = sorted({yahoo.benchmark_for(t) for t in sampled})
    report = {"tickers": [], "benchmarks": benches, "prices_rows": 0, "statement_rows": 0, "no_prices": []}
    now = datetime.now(timezone.utc)
    for t in sampled + benches:
        if t in have:
            continue
        prices = yahoo.fetch_prices(t)
        n_p = _upsert_prices(con, prices)
        n_s = 0
        if t in sampled:
            n_s = _upsert_statements(con, yahoo.fetch_statements(t))
        info = yahoo.fetch_info(t) if t in sampled else {"name": t, "exchange": None, "currency": None}
        first, last = yahoo.first_last(prices)
        ok = n_p > 0
        con.execute(
            """INSERT OR REPLACE INTO vi.tickers (ticker, name, exchange, currency, benchmark, yahoo_ok, first_price, last_price, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [t, info["name"], info["exchange"], info["currency"], yahoo.benchmark_for(t) if t in sampled else None, ok, first, last, now],
        )
        report["prices_rows"] += n_p
        report["statement_rows"] += n_s
        if not ok:
            report["no_prices"].append(t)
        report["tickers"].append({"ticker": t, "prices": n_p, "statements": n_s, "first": str(first), "last": str(last)})
        print(f"  {t:12s} prices={n_p:5d} statements={n_s:4d} {first}→{last}", flush=True)
    return report
