"""Forward-return validation — were the calls any good? (spec §Validation, D14)

For every eval and horizon h ∈ {6, 12, 24} months with T0 + h ≤ the last price:
ret = close(T0+h) / close(T0) − 1, bench_ret the same for the benchmark,
excess = ret − bench_ret. Verdict: BUY correct if excess > +5 pp, wrong if
< −5 pp; SELL the mirror; HOLD correct if |excess| ≤ 10 pp (D14), with the
"did not lag by > 5 pp" view kept beside it. iv_hit: the price touched his
stated intrinsic value inside the horizon."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import duckdb

from value_invest.config import settings

BAND = 0.05
HOLD_BAND = 0.10


def verdict_for(position: str, excess: float) -> str:
    if position == "BUY":
        return "correct" if excess > BAND else "wrong" if excess < -BAND else "indeterminate"
    if position == "SELL":
        return "correct" if excess < -BAND else "wrong" if excess > BAND else "indeterminate"
    return "correct" if abs(excess) <= HOLD_BAND else "wrong"


def verdict_hold_alt(position: str, excess: float) -> str:
    if position != "HOLD":
        return verdict_for(position, excess)
    return "correct" if excess >= -BAND else "wrong"


def _close_on_or_before(
    con: duckdb.DuckDBPyConnection, ticker: str, d: date
) -> tuple[date, float] | None:
    r = con.execute(
        "SELECT date, adj_close FROM vi.prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
        [ticker, d],
    ).fetchone()
    return (r[0], float(r[1])) if r and r[1] is not None else None


def validate_all(
    con: duckdb.DuckDBPyConnection, video_ids: list[str] | None = None
) -> dict[str, Any]:
    s = settings()
    last_row = con.execute("SELECT max(date) FROM vi.prices").fetchone()
    last = last_row[0] if last_row else None
    if last is None:
        return {"rows_written": 0, "n_evals": 0}
    rows = con.execute(
        """SELECT e.video_id, e.ticker, e.t0, e.position, e.iv_weighted_stated, coalesce(t.benchmark, ?)
           FROM vi.evals e LEFT JOIN vi.tickers t ON t.ticker = e.ticker ORDER BY e.t0""",
        [s.default_benchmark],
    ).fetchall()
    if video_ids:
        rows = [r for r in rows if r[0] in set(video_ids)]
    written = 0
    for vid, ticker, t0, position, iv, bench in rows:
        p0 = _close_on_or_before(con, ticker, t0)
        b0 = _close_on_or_before(con, bench, t0)
        if not p0 or not b0:
            continue
        for h in s.horizons_months:
            t1 = t0 + timedelta(days=int(h * 30.4375))
            if t1 > last:
                continue
            p1 = _close_on_or_before(con, ticker, t1)
            b1 = _close_on_or_before(con, bench, t1)
            if not p1 or not b1:
                continue
            ret = p1[1] / p0[1] - 1
            bret = b1[1] / b0[1] - 1
            ex = ret - bret
            iv_hit = None
            if iv:
                lohi = con.execute(
                    "SELECT min(adj_close), max(adj_close) FROM vi.prices WHERE ticker = ? AND date > ? AND date <= ?",
                    [ticker, t0, t1],
                ).fetchone()
                if lohi and lohi[0] is not None:
                    lo, hi, at0 = lohi[0], lohi[1], p0[1]
                    iv_hit = (hi >= iv) if iv >= at0 else (lo <= iv)
            con.execute(
                """INSERT OR REPLACE INTO vi.validations (video_id, horizon_m, t0, t1, ret, bench_ret, excess, verdict, verdict_hold_alt, iv_hit)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    vid,
                    h,
                    t0,
                    p1[0],
                    ret,
                    bret,
                    ex,
                    verdict_for(position, ex),
                    verdict_hold_alt(position, ex),
                    iv_hit,
                ],
            )
            written += 1
    summary = validation_summary(con)
    summary["rows_written"] = written
    summary["last_price_date"] = str(last)
    return summary


def validation_summary(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Per window year × horizon: n, mix, hit rates per class, verdict counts; plus overall."""
    rows = con.execute(
        """SELECT v.year_bucket, val.horizon_m, e.position, val.excess, val.verdict, val.verdict_hold_alt, val.iv_hit,
                  e.stance_detail, e.expected_return_pct, e.split
           FROM vi.validations val JOIN vi.evals e USING (video_id) JOIN vi.videos v USING (video_id)"""
    ).fetchall()
    out: dict[str, Any] = {"by_year": {}, "overall": {}}

    def bucket(
        target: dict[str, Any],
        key: str,
        position: str,
        ex: float,
        verdict: str,
        alt: str,
        iv_hit: bool | None,
    ) -> None:
        b = target.setdefault(
            key,
            {
                "n": 0,
                "mix": {"BUY": 0, "HOLD": 0, "SELL": 0},
                "hits": {"BUY": [0, 0], "HOLD": [0, 0], "SELL": [0, 0]},
                "mean_excess": {"BUY": [], "HOLD": [], "SELL": []},
                "verdict": {"correct": 0, "wrong": 0, "indeterminate": 0},
                "verdict_hold_alt": {"correct": 0, "wrong": 0, "indeterminate": 0},
                "iv_hit": [0, 0],
            },
        )
        b["n"] += 1
        b["mix"][position] += 1
        b["hits"][position][1] += 1
        b["hits"][position][0] += int(verdict == "correct")
        b["mean_excess"][position].append(ex)
        b["verdict"][verdict] += 1
        b["verdict_hold_alt"][alt] += 1
        if iv_hit is not None:
            b["iv_hit"][1] += 1
            b["iv_hit"][0] += int(bool(iv_hit))

    for yb, h, pos, ex, verdict, alt, iv_hit, *_ in rows:
        bucket(out["by_year"].setdefault(yb, {}), str(h), pos, ex, verdict, alt, iv_hit)
        bucket(out["overall"], str(h), pos, ex, verdict, alt, iv_hit)
    for group in [out["overall"], *out["by_year"].values()]:
        for b in group.values():
            b["mean_excess"] = {
                k: (round(sum(v) / len(v) * 100, 1) if v else None)
                for k, v in b["mean_excess"].items()
            }
    splits = con.execute("SELECT split, count(*) FROM vi.evals GROUP BY 1").fetchall()
    out["splits"] = {k: n for k, n in splits}
    n_row = con.execute("SELECT count(*) FROM vi.evals").fetchone()
    out["n_evals"] = n_row[0] if n_row else 0
    return out
