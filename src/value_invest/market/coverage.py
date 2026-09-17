"""S2 — per-video coverage: is there a price at T0, and how many *complete*
fiscal years are visible at T0 under the annual-only rule? (yfinance's oldest
column is a stub without revenue or net income — see vi.fiscal_years.)"""

from __future__ import annotations

import duckdb

SQL = """
WITH v AS (
  SELECT video_id, title, published_at AS t0, primary_ticker AS ticker, year_bucket, sample_rank
  FROM vi.videos WHERE in_sample
),
px AS (
  SELECT v.video_id, p.close AS price_at_t0, p.date AS price_date
  FROM v LEFT JOIN LATERAL (
    SELECT close, date FROM vi.prices WHERE ticker = v.ticker AND date <= v.t0 ORDER BY date DESC LIMIT 1
  ) p ON TRUE
),
st AS (
  SELECT v.video_id,
         count(*) FILTER (WHERE f.complete AND f.available_from <= v.t0) AS fys_visible,
         count(*) FILTER (WHERE NOT f.complete AND f.available_from <= v.t0) AS stub_fys_visible,
         max(f.period_end) FILTER (WHERE f.complete AND f.available_from <= v.t0) AS latest_fy_visible,
         count(*) FILTER (WHERE f.complete) AS fys_total,
         min(f.period_end) FILTER (WHERE f.complete) AS earliest_fy
  FROM v LEFT JOIN vi.fiscal_years f ON f.ticker = v.ticker
  GROUP BY v.video_id
)
SELECT v.video_id, v.title, v.t0, v.ticker, v.year_bucket, v.sample_rank,
       px.price_at_t0, px.price_date,
       st.fys_visible, st.stub_fys_visible, st.latest_fy_visible, st.fys_total, st.earliest_fy,
       t.yahoo_ok, t.currency, t.benchmark,
       CASE WHEN px.price_at_t0 IS NULL THEN 'no_prices'
            WHEN coalesce(st.fys_visible, 0) = 0 THEN 'prices_only'
            WHEN st.fys_visible >= 3 THEN 'full' ELSE 'shallow' END AS coverage
FROM v LEFT JOIN px USING (video_id) LEFT JOIN st USING (video_id)
LEFT JOIN vi.tickers t ON t.ticker = v.ticker
ORDER BY v.t0
"""


def coverage_table(con: duckdb.DuckDBPyConnection) -> list[dict]:
    cur = con.execute(SQL)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def coverage_summary(rows: list[dict]) -> dict:
    out: dict[str, int] = {}
    for r in rows:
        out[r["coverage"]] = out.get(r["coverage"], 0) + 1
    return out
