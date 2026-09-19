"""The walkthrough app: read-only JSON over DuckDB + transcript·lab's corpus,
serving the built React bundle from one origin. No model is ever called here."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from value_invest import db
from value_invest.config import ROOT, settings
from value_invest.market.coverage import coverage_summary, coverage_table
from value_invest.serving import sql as sqlviewer

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


class ReviewRequest(BaseModel):
    """A human label from the Golden Evals / Video tab — the one write the app makes."""

    curation_status: str
    note: str | None = None
    stance_detail: str | None = None


class SqlRequest(BaseModel):
    """Module-level on purpose: with ``from __future__ import annotations`` FastAPI
    cannot resolve a class defined inside ``create_app`` and treats it as a query param."""

    sql: str
    max_rows: int = sqlviewer.MAX_ROWS


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
            "milestone": "M2",
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
            # Columns are fiscal-year labels (year of period end) so EDGAR and
            # yfinance rows for the same year share one column; when both hold a
            # value the EDGAR one (real filing date) wins.
            st = _rows(
                c,
                "SELECT period_end, kind, line_item, value, available_from, source "
                "FROM vi.statements_as_of(?, ?) ORDER BY period_end DESC, source",
                [ticker, t0],
            )
            fy_rows = {
                int(r["fy"]): r
                for r in _rows(
                    c,
                    "SELECT fy, period_end, n_items, complete, from_edgar FROM vi.fiscal_years WHERE ticker = ?",
                    [ticker],
                )
            }
            periods = sorted({str(r["period_end"])[:4] for r in st}, reverse=True)
            out["statement_periods"] = periods
            out["statement_period_info"] = [
                {
                    "period_end": p,
                    "n_items": fy_rows.get(int(p), {}).get("n_items"),
                    "complete": bool(fy_rows.get(int(p), {}).get("complete")),
                    "from_edgar": bool(fy_rows.get(int(p), {}).get("from_edgar")),
                }
                for p in periods
            ]
            by_kind: dict[str, dict[str, dict[str, float]]] = {}
            for r in st:
                cell = by_kind.setdefault(r["kind"], {}).setdefault(r["line_item"], {})
                key = str(r["period_end"])[:4]
                if key not in cell or r["source"] == "edgar":
                    cell[key] = r["value"]
            out["statements"] = {
                k: {"headline": [i for i in HEADLINE_ITEMS[k] if i in items], "items": items}
                for k, items in by_kind.items()
            }
            hidden = _rows(
                c,
                "SELECT period_end, available_from FROM vi.fiscal_years WHERE ticker = ? AND available_from > ? ORDER BY 1",
                [ticker, t0],
            )
            out["statements_hidden_after_t0"] = hidden
            cov = [r for r in coverage_table(c) if r["video_id"] == video_id]
            out["coverage"] = cov[0] if cov else None
        ev = _rows(c, "SELECT * FROM vi.evals WHERE video_id = ?", [video_id])
        if ev:
            e = ev[0]
            for k in (
                "valuation",
                "iv_recomputed",
                "reasons",
                "external_facts",
                "critic",
                "checks",
            ):
                if isinstance(e.get(k), str):
                    e[k] = json.loads(e[k])
            e["validations"] = _rows(
                c,
                "SELECT horizon_m, t1, ret, bench_ret, excess, verdict, verdict_hold_alt, iv_hit FROM vi.validations WHERE video_id = ? ORDER BY horizon_m",
                [video_id],
            )
            out["eval"] = e
        else:
            out["eval"] = None
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

    @app.get("/api/sql/catalog")
    def sql_catalog() -> dict:
        return sqlviewer.catalog(con())

    @app.post("/api/sql")
    def sql_run(req: SqlRequest) -> dict:
        try:
            return sqlviewer.run_select(con(), req.sql, max_rows=min(max(1, req.max_rows), 5000))
        except sqlviewer.SqlError as e:
            raise HTTPException(400, str(e)) from e

    # ---------------------------------------------------------------- M2: golden evals

    JSON_COLS = ("valuation", "iv_recomputed", "reasons", "external_facts", "critic", "checks")

    def _decode(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for r in rows:
            for k in JSON_COLS:
                if k in r and isinstance(r[k], str):
                    r[k] = json.loads(r[k])
        return rows

    @app.get("/api/evals")
    def evals(
        year: str | None = None, position: str | None = None, split: str | None = None
    ) -> list[dict]:
        c = con()
        where, params = [], []
        if year:
            where.append("v.year_bucket = ?")
            params.append(year)
        if position:
            where.append("e.position = ?")
            params.append(position)
        if split:
            where.append("e.split = ?")
            params.append(split)
        w = ("WHERE " + " AND ".join(where)) if where else ""
        rows = _rows(
            c,
            f"""SELECT e.video_id, e.ticker, e.t0, v.title, v.year_bucket, e.position, e.binary_position, e.hurdle_position,
                       e.stance_detail, e.personal_action, e.expected_return_pct, e.conviction, e.rule_sensitive, e.title_says_buy,
                       e.iv_weighted_stated, e.price_at_t0, e.split, e.curation_status, e.extractor_version, e.checks, e.critic,
                       e.reasons, e.headline_quote,
                       (SELECT json_group_object(horizon_m, json_object('excess', excess, 'verdict', verdict, 'verdict_hold_alt', verdict_hold_alt, 'iv_hit', iv_hit, 't1', t1))
                          FROM vi.validations val WHERE val.video_id = e.video_id) AS validations
                FROM (SELECT *, CASE WHEN position = 'BUY' THEN 'BUY' ELSE 'SELL' END AS binary_position,
                             CASE WHEN expected_return_pct IS NULL THEN NULL WHEN expected_return_pct >= 10 THEN 'BUY'
                                  WHEN position = 'SELL' THEN 'SELL' ELSE 'HOLD' END AS hurdle_position FROM vi.evals) e
                JOIN vi.videos v USING (video_id) {w}
                ORDER BY e.rule_sensitive DESC, e.t0""",
            params,
        )
        for r in rows:
            r["validations"] = json.loads(r["validations"]) if r.get("validations") else {}
            r["reasons"] = (
                json.loads(r["reasons"]) if isinstance(r.get("reasons"), str) else r.get("reasons")
            )
            r["n_reasons"] = len(r["reasons"] or [])
            r["reason_categories"] = [x["category"] for x in (r["reasons"] or [])]
            del r["reasons"]
        return _decode(rows)

    @app.get("/api/evals/summary")
    def evals_summary() -> dict:
        from value_invest.golden.validate import validation_summary

        c = con()
        out: dict[str, Any] = {"validation": validation_summary(c)}
        out["mix"] = _rows(
            c,
            """SELECT v.year_bucket, e.split, count(*) AS n,
                      count(*) FILTER (WHERE e.position = 'BUY') AS buy,
                      count(*) FILTER (WHERE e.position = 'HOLD') AS hold,
                      count(*) FILTER (WHERE e.position = 'SELL') AS sell,
                      count(*) FILTER (WHERE e.curation_status = 'reviewed') AS reviewed,
                      count(*) FILTER (WHERE e.rule_sensitive) AS rule_sensitive
               FROM vi.evals e JOIN vi.videos v USING (video_id) GROUP BY 1, 2 ORDER BY 1""",
        )
        out["cuts"] = _rows(
            c,
            """SELECT 'C · 3-way' AS rule, position AS label, count(*) AS n FROM vi.evals GROUP BY 2
               UNION ALL SELECT 'A · binary', CASE WHEN position = 'BUY' THEN 'BUY' ELSE 'SELL' END, count(*) FROM vi.evals GROUP BY 2
               UNION ALL SELECT 'B · hurdle', CASE WHEN expected_return_pct IS NULL THEN 'n/a' WHEN expected_return_pct >= 10 THEN 'BUY' WHEN position = 'SELL' THEN 'SELL' ELSE 'HOLD' END, count(*) FROM vi.evals GROUP BY 2
               ORDER BY 1, 2""",
        )
        stats = _rows(
            c,
            """SELECT count(*) AS n, count(*) FILTER (WHERE curation_status = 'reviewed') AS reviewed,
                      count(*) FILTER (WHERE rule_sensitive) AS rule_sensitive, count(*) FILTER (WHERE title_says_buy AND position <> 'BUY') AS title_mismatch,
                      count(*) FILTER (WHERE iv_weighted_stated IS NOT NULL) AS with_iv,
                      avg(CAST(json_extract(checks, '$.reproducible_share') AS DOUBLE)) AS reproducible_share,
                      avg(CAST(json_extract(checks, '$.faithful_share') AS DOUBLE)) AS faithful_share,
                      count(*) FILTER (WHERE CAST(json_extract(checks, '$.price_check') AS BOOLEAN)) AS price_ok,
                      count(*) FILTER (WHERE json_extract(checks, '$.price_check') IS NOT NULL AND json_extract(checks, '$.price_check') <> 'null') AS price_n,
                      sum(CAST(json_extract(checks, '$.iv_ok') AS INTEGER)) AS iv_ok, sum(CAST(json_extract(checks, '$.iv_compared') AS INTEGER)) AS iv_compared,
                      count(*) FILTER (WHERE abs(coalesce(CAST(json_extract(checks, '$.base_metric_gap_pct') AS DOUBLE), 0)) > 15) AS base_gap_over_15,
                      count(*) FILTER (WHERE CAST(json_extract(critic, '$.position_agrees') AS BOOLEAN)) AS critic_agrees,
                      count(*) FILTER (WHERE critic IS NOT NULL) AS critic_n
               FROM vi.evals""",
        )
        out["stats"] = stats[0] if stats else {}
        repro = _rows(
            c,
            """SELECT r.reproducible, count(*) AS n FROM (
                 SELECT json_extract_string(unnest(from_json(reasons, '["JSON"]')), '$.data_check.reproducible') AS reproducible FROM vi.evals) r
               GROUP BY 1 ORDER BY 2 DESC""",
        )
        out["reproducible"] = repro
        for name in ("seed_eval_v0", "kappa", "method_summary"):
            p = ROOT / "data" / "golden" / f"{name}.json"
            if p.exists():
                d = json.loads(p.read_text())
                d.pop("rows", None)
                out[name] = d
        return out

    @app.get("/api/evals/{video_id}")
    def eval_detail(video_id: str) -> dict:
        c = con()
        rows = _decode(
            _rows(
                c,
                "SELECT e.*, v.title, v.year_bucket FROM vi.evals e JOIN vi.videos v USING (video_id) WHERE e.video_id = ?",
                [video_id],
            )
        )
        if not rows:
            raise HTTPException(404, "no eval for this video")
        r = rows[0]
        r["validations"] = _rows(
            c, "SELECT * FROM vi.validations WHERE video_id = ? ORDER BY horizon_m", [video_id]
        )
        r["binary_position"] = "BUY" if r["position"] == "BUY" else "SELL"
        er = r.get("expected_return_pct")
        r["hurdle_position"] = (
            None
            if er is None
            else ("BUY" if er >= 10 else ("SELL" if r["position"] == "SELL" else "HOLD"))
        )
        return r

    @app.post("/api/evals/{video_id}/review")
    def review(video_id: str, req: ReviewRequest) -> dict:
        from datetime import datetime, timezone

        from value_invest.golden.models import THREE_WAY

        if req.curation_status not in ("auto", "reviewed", "rejected"):
            raise HTTPException(400, "curation_status must be auto | reviewed | rejected")
        if req.stance_detail and req.stance_detail not in THREE_WAY:
            raise HTTPException(400, "unknown stance_detail")
        w = db.connect()  # the one write the app makes: a human label
        try:
            if req.stance_detail:
                w.execute(
                    "UPDATE vi.evals SET stance_detail = ?, position = ? WHERE video_id = ?",
                    [req.stance_detail, THREE_WAY[req.stance_detail], video_id],
                )
            w.execute(
                "UPDATE vi.evals SET curation_status = ?, review_note = ?, reviewed_at = ? WHERE video_id = ?",
                [req.curation_status, req.note, datetime.now(timezone.utc), video_id],
            )
            row = w.execute(
                "SELECT ticker, t0, stance_detail, position FROM vi.evals WHERE video_id = ?",
                [video_id],
            ).fetchone()
        finally:
            w.close()
        if not row:
            raise HTTPException(404, "no eval for this video")
        # every review is a human label: append/replace in the seed file
        seed_path = ROOT / "data" / "golden" / "seed_labels.json"
        try:
            seed = json.loads(seed_path.read_text())
            labels = [x for x in seed["labels"] if x["video_id"] != video_id]
            prior = next((x for x in seed["labels"] if x["video_id"] == video_id), {})
            labels.append(
                {
                    **prior,
                    "video_id": video_id,
                    "ticker": row[0],
                    "t0": str(row[1]),
                    "read": prior.get("read", "app"),
                    "stance_detail": row[2],
                    "source": "human",
                    "curation_status": req.curation_status,
                    "note": req.note or prior.get("note"),
                }
            )
            seed["labels"] = sorted(labels, key=lambda x: x["t0"])
            seed_path.write_text(json.dumps(seed, indent=1, ensure_ascii=False))
        except OSError:
            pass
        return {
            "video_id": video_id,
            "curation_status": req.curation_status,
            "stance_detail": row[2],
            "position": row[3],
        }

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
