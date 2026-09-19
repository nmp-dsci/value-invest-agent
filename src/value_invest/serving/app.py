"""The walkthrough app: read-only JSON over DuckDB + transcript·lab's corpus,
serving the built React bundle from one origin. No model is ever called here."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from value_invest import db
from value_invest.config import ROOT, settings
from value_invest.market.coverage import coverage_summary, coverage_table

DIST = ROOT / "frontend" / "dist"

# Line items the Video page shows per statement kind (yfinance names). Everything
# else stays in the table as "more".
HEADLINE_ITEMS = {
    "income": [
        "Total Revenue",
        "Gross Profit",
        "Operating Income",
        "EBITDA",
        "Net Income",
        "Diluted EPS",
    ],
    "balance": [
        "Total Assets",
        "Total Debt",
        "Cash And Cash Equivalents",
        "Stockholders Equity",
        "Net Debt",
        "Working Capital",
    ],
    "cashflow": [
        "Operating Cash Flow",
        "Capital Expenditure",
        "Free Cash Flow",
        "Cash Dividends Paid",
        "Repurchase Of Capital Stock",
    ],
}


def _rows(con, sql: str, params: list | None = None) -> list[dict[str, Any]]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def create_app() -> FastAPI:
    app = FastAPI(title="value·invest agent", version="0.1.0")
    s = settings()

    def con():
        return db.connect(read_only=True)

    @app.get("/api/health")
    def health() -> dict:
        c = con()
        return {
            "ok": True,
            "mode": "demo" if s.demo_mode else "dev",
            "tables": db.table_counts(c),
            "milestone": "M1",
        }

    @app.get("/api/funnel")
    def funnel() -> dict:
        c = con()
        listed = c.execute("SELECT count(*) FROM vi.videos").fetchone()[0]
        in_window = c.execute(
            "SELECT count(*) FROM vi.videos WHERE year_bucket IS NOT NULL"
        ).fetchone()[0]
        kinds = _rows(
            c,
            "SELECT coalesce(kind,'unlabelled') AS kind, count(*) AS n FROM vi.videos WHERE year_bucket IS NOT NULL GROUP BY 1 ORDER BY 2 DESC",
        )
        per_year = _rows(
            c,
            """SELECT year_bucket, count(*) AS videos,
                                 count(*) FILTER (WHERE kind='single') AS single,
                                 count(*) FILTER (WHERE in_sample) AS sampled,
                                 count(*) FILTER (WHERE in_sample AND transcript_status='indexed') AS indexed
                               FROM vi.videos WHERE year_bucket IS NOT NULL GROUP BY 1 ORDER BY 1""",
        )
        sampled = c.execute("SELECT count(*) FROM vi.videos WHERE in_sample").fetchone()[0]
        indexed = c.execute(
            "SELECT count(*) FROM vi.videos WHERE in_sample AND transcript_status='indexed'"
        ).fetchone()[0]
        return {
            "listed": listed,
            "in_window": in_window,
            "kinds": kinds,
            "per_year": per_year,
            "sampled": sampled,
            "indexed": indexed,
            "since": str(s.since),
            "until": str(s.until),
            "per_year_target": s.sample_per_year,
            "seed": s.sample_seed,
        }

    @app.get("/api/videos")
    def videos(
        sample: bool = True, kind: str | None = None, year: str | None = None, limit: int = 2000
    ) -> list[dict]:
        c = con()
        where, params = [], []
        if sample:
            where.append("v.in_sample")
        if kind:
            where.append("v.kind = ?")
            params.append(kind)
        if year:
            where.append("v.year_bucket = ?")
            params.append(year)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        rows = _rows(
            c,
            f"""SELECT v.video_id, v.title, v.published_at, v.duration_s, v.view_count, v.kind, v.primary_ticker,
                                   v.year_bucket, v.in_sample, v.sample_rank, v.transcript_status, v.transcript_segments,
                                   l.confidence, l.rationale, l.tickers, t.name AS company, t.currency
                            FROM vi.videos v LEFT JOIN vi.title_labels l USING (video_id)
                            LEFT JOIN vi.tickers t ON t.ticker = v.primary_ticker
                            {w} ORDER BY v.published_at DESC LIMIT {int(limit)}""",
            params,
        )
        for r in rows:
            r["tickers"] = json.loads(r["tickers"]) if r.get("tickers") else []
        return rows

    @app.get("/api/videos/{video_id}")
    def video(video_id: str, before_days: int = 5 * 365, after_days: int = 40 * 365) -> dict:
        """Prices for the chart: five years before T0 and everything available after it."""
        c = con()
        v = _rows(
            c,
            """SELECT v.*, l.confidence, l.rationale, l.tickers, t.name AS company, t.currency, t.exchange, t.benchmark
                        FROM vi.videos v LEFT JOIN vi.title_labels l USING (video_id)
                        LEFT JOIN vi.tickers t ON t.ticker = v.primary_ticker WHERE v.video_id = ?""",
            [video_id],
        )
        if not v:
            raise HTTPException(404, "unknown video")
        row = v[0]
        row["tickers"] = json.loads(row["tickers"]) if row.get("tickers") else []
        t0: date | None = row["published_at"]
        ticker = row["primary_ticker"]
        out: dict[str, Any] = {
            "video": row,
            "t0": t0,
            "prices": [],
            "benchmark": [],
            "statements": {},
            "statement_periods": [],
            "transcript": None,
            "chunks": [],
            "coverage": None,
        }
        if ticker and t0:
            lo, hi = t0 - timedelta(days=before_days), t0 + timedelta(days=after_days)
            out["prices"] = _rows(
                c,
                "SELECT date, close, adj_close FROM vi.prices WHERE ticker = ? AND date BETWEEN ? AND ? ORDER BY date",
                [ticker, lo, hi],
            )
            if row.get("benchmark"):
                out["benchmark"] = _rows(
                    c,
                    "SELECT date, adj_close FROM vi.prices WHERE ticker = ? AND date BETWEEN ? AND ? ORDER BY date",
                    [row["benchmark"], lo, hi],
                )
            at = _rows(
                c,
                "SELECT date, close FROM vi.prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
                [ticker, t0],
            )
            out["price_at_t0"] = at[0] if at else None
            # forward prices for the eventual validator — shown, never fed to an agent
            fwd = {}
            for m in s.horizons_months:
                d = t0 + timedelta(days=int(m * 30.44))
                r = _rows(
                    c,
                    "SELECT date, close FROM vi.prices WHERE ticker = ? AND date >= ? ORDER BY date LIMIT 1",
                    [ticker, d],
                )
                fwd[str(m)] = r[0] if r and r[0]["date"] <= date.today() else None
            out["forward"] = fwd
            # as-of statements: only fiscal years visible at t0
            st = _rows(
                c,
                "SELECT period_end, kind, line_item, value, available_from FROM vi.statements_as_of(?, ?) ORDER BY period_end DESC",
                [ticker, t0],
            )
            periods = sorted({r["period_end"] for r in st}, reverse=True)
            out["statement_periods"] = periods
            fy = {
                r["period_end"]: r
                for r in _rows(
                    c,
                    "SELECT period_end, n_items, complete FROM vi.fiscal_years WHERE ticker = ?",
                    [ticker],
                )
            }
            out["statement_period_info"] = [
                {
                    "period_end": p,
                    "n_items": fy.get(p, {}).get("n_items"),
                    "complete": bool(fy.get(p, {}).get("complete")),
                }
                for p in periods
            ]
            by_kind: dict[str, dict[str, dict[str, float]]] = {}
            for r in st:
                by_kind.setdefault(r["kind"], {}).setdefault(r["line_item"], {})[
                    str(r["period_end"])
                ] = r["value"]
            out["statements"] = {
                k: {"headline": [i for i in HEADLINE_ITEMS[k] if i in items], "items": items}
                for k, items in by_kind.items()
            }
            hidden = _rows(
                c,
                "SELECT DISTINCT period_end, available_from FROM vi.statements WHERE ticker = ? AND available_from > ? ORDER BY 1",
                [ticker, t0],
            )
            out["statements_hidden_after_t0"] = hidden
            cov = [r for r in coverage_table(c) if r["video_id"] == video_id]
            out["coverage"] = cov[0] if cov else None
        try:
            from value_invest.ingest.corpus import corpus

            raw = corpus().raw(video_id)
            if raw:
                out["transcript"] = raw
                out["chunks"] = corpus().chunks(video_id)
        except Exception as e:  # corpus unavailable: the page still renders
            out["transcript_error"] = str(e)[:200]
        return out

    @app.get("/api/market/coverage")
    def coverage() -> dict:
        c = con()
        rows = coverage_table(c)
        tickers = _rows(
            c,
            """SELECT t.* FROM vi.tickers t
                                WHERE t.ticker IN (SELECT primary_ticker FROM vi.videos WHERE in_sample)
                                   OR t.ticker IN (SELECT benchmark FROM vi.tickers WHERE ticker IN (SELECT primary_ticker FROM vi.videos WHERE in_sample))
                                ORDER BY t.benchmark IS NULL, t.ticker""",
        )
        return {"rows": rows, "summary": coverage_summary(rows), "tickers": tickers}

    @app.get("/api/calls")
    def calls() -> list[dict]:  # M2 stub
        return _rows(con(), "SELECT * FROM vi.calls ORDER BY t0")

    if DIST.exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/favicon.svg")
        def favicon() -> FileResponse:
            return FileResponse(DIST / "favicon.svg", media_type="image/svg+xml")

        @app.get("/{path:path}")
        def spa(path: str) -> FileResponse:
            f = DIST / path
            return FileResponse(f if f.is_file() else DIST / "index.html")

    return app
