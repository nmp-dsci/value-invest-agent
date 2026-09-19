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
    con.execute(
        "INSERT OR REPLACE INTO vi.prices SELECT ticker, date, open, high, low, close, adj_close, CAST(volume AS BIGINT) FROM _p"
    )
    con.unregister("_p")
    return len(df)


def _upsert_statements(con: duckdb.DuckDBPyConnection, df) -> int:
    if df.empty:
        return 0
    con.register("_s", df)
    con.execute(
        "INSERT OR REPLACE INTO vi.statements SELECT ticker, period_end, kind, freq, line_item, value, filed_at, available_from, source FROM _s"
    )
    con.unregister("_s")
    return len(df)


def check_edgar_candidates(con: duckdb.DuckDBPyConnection) -> dict:
    """Mark every single-stock candidate's ticker as an EDGAR 10-K filer or not, so
    the sample can be restricted to US stocks with SEC filings."""
    from value_invest.market.edgar import Edgar, check_filer

    client = Edgar()
    tickers = [
        r[0]
        for r in con.execute(
            """SELECT DISTINCT v.primary_ticker FROM vi.videos v
               LEFT JOIN vi.tickers t ON t.ticker = v.primary_ticker
               WHERE v.kind = 'single' AND v.year_bucket IS NOT NULL AND v.primary_ticker IS NOT NULL
                 AND t.edgar_filer IS NULL ORDER BY 1"""
        ).fetchall()
    ]
    filers, non = 0, 0
    for t in tickers:
        try:
            cik, ok = check_filer(t, client)
        except Exception as e:  # keep going; unknown stays NULL for a re-run
            print(f"  {t}: {str(e)[:80]}", flush=True)
            continue
        con.execute(
            """INSERT INTO vi.tickers (ticker, cik, edgar_filer) VALUES (?, ?, ?)
               ON CONFLICT (ticker) DO UPDATE SET cik = excluded.cik, edgar_filer = excluded.edgar_filer""",
            [t, cik, ok],
        )
        filers += ok
        non += not ok
    total = con.execute(
        "SELECT count(*) FILTER (WHERE edgar_filer), count(*) FILTER (WHERE edgar_filer = FALSE) FROM vi.tickers"
    ).fetchone()
    return {
        "checked": len(tickers),
        "filers": filers,
        "non_filers": non,
        "edgar_calls": client.calls,
        "totals": {"filers": total[0], "non_filers": total[1]},
    }


def load_edgar(con: duckdb.DuckDBPyConnection, tickers: list[str] | None = None) -> dict:
    """10+ years of annual statements with filing dates for the US filers among
    the sampled tickers (EDGAR companyfacts). Rows replace yfinance rows for the
    same (ticker, period_end, kind, line_item); non-filers are reported, not failed."""
    from value_invest.market.edgar import Edgar, fetch_edgar_statements

    client = Edgar()
    sampled = tickers or [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT primary_ticker FROM vi.videos WHERE in_sample AND primary_ticker IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
    report: dict = {"filers": [], "not_on_edgar": [], "statement_rows": 0, "edgar_calls": 0}
    for t in sampled:
        try:
            df = fetch_edgar_statements(t, client)
        except Exception as e:  # one bad ticker must not stop the batch
            report.setdefault("errors", []).append(f"{t}: {str(e)[:120]}")
            continue
        if df is None or df.empty:
            report["not_on_edgar"].append(t)
            continue
        n = _upsert_statements(con, df)
        years = sorted({int(str(p)[:4]) for p in df["period_end"]})
        report["filers"].append(
            {"ticker": t, "rows": n, "fiscal_years": f"{years[0]}–{years[-1]} ({len(years)})"}
        )
        report["statement_rows"] += n
        con.execute("UPDATE vi.tickers SET fundamentals_source = 'edgar' WHERE ticker = ?", [t])
        print(f"  {t:10s} edgar rows={n:4d} FY {years[0]}–{years[-1]}", flush=True)
    report["edgar_calls"] = client.calls
    return report


def load_market(
    con: duckdb.DuckDBPyConnection, only_missing: bool = True, tickers: list[str] | None = None
) -> dict:
    sampled = tickers or [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT primary_ticker FROM vi.videos WHERE in_sample AND primary_ticker IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
    have = (
        {r[0] for r in con.execute("SELECT ticker FROM vi.tickers WHERE yahoo_ok").fetchall()}
        if only_missing
        else set()
    )
    benches = sorted({yahoo.benchmark_for(t) for t in sampled})
    report = {
        "tickers": [],
        "benchmarks": benches,
        "prices_rows": 0,
        "statement_rows": 0,
        "no_prices": [],
    }
    now = datetime.now(timezone.utc)
    for t in sampled + benches:
        if t in have:
            continue
        prices = yahoo.fetch_prices(t)
        n_p = _upsert_prices(con, prices)
        n_s = 0
        if t in sampled:
            n_s = _upsert_statements(con, yahoo.fetch_statements(t))
        info = (
            yahoo.fetch_info(t) if t in sampled else {"name": t, "exchange": None, "currency": None}
        )
        first, last = yahoo.first_last(prices)
        ok = n_p > 0
        con.execute(
            """INSERT OR REPLACE INTO vi.tickers (ticker, name, exchange, currency, benchmark, yahoo_ok, first_price, last_price, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                t,
                info["name"],
                info["exchange"],
                info["currency"],
                yahoo.benchmark_for(t) if t in sampled else None,
                ok,
                first,
                last,
                now,
            ],
        )
        report["prices_rows"] += n_p
        report["statement_rows"] += n_s
        if not ok:
            report["no_prices"].append(t)
        report["tickers"].append(
            {"ticker": t, "prices": n_p, "statements": n_s, "first": str(first), "last": str(last)}
        )
        print(f"  {t:12s} prices={n_p:5d} statements={n_s:4d} {first}→{last}", flush=True)
    return report
