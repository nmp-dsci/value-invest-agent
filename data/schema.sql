-- The vi schema. Applied by `vi db init`; idempotent.
-- Everything below vi.videos is derived and rebuildable from the caches under .vi/.
CREATE SCHEMA IF NOT EXISTS vi;

CREATE TABLE IF NOT EXISTS vi.videos (
  video_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT,
  published_at DATE,
  duration_s INTEGER,
  view_count BIGINT,
  kind TEXT,                       -- single | multi | macro | other  (from vi.title_labels)
  primary_ticker TEXT,             -- yahoo ticker of the video's subject when kind = single
  year_bucket TEXT,                -- window year label, e.g. '2022/23'
  in_sample BOOLEAN DEFAULT FALSE,
  sample_rank INTEGER,             -- order within the seeded draw (1 = first pick)
  transcript_status TEXT DEFAULT 'none',   -- none | indexed | failed
  transcript_segments INTEGER,
  date_source TEXT,                -- supadata | yt-dlp (exact) | approx (channel tab) | undated
  catalogued_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vi.title_labels (
  video_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  tickers JSON NOT NULL,           -- [{company, yahoo_ticker, exchange, is_primary}]
  confidence DOUBLE,
  rationale TEXT,
  source TEXT NOT NULL,            -- llm | human
  classifier_version TEXT,
  labelled_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vi.tickers (
  ticker TEXT PRIMARY KEY,
  name TEXT,
  exchange TEXT,
  currency TEXT,
  benchmark TEXT,
  yahoo_ok BOOLEAN,
  fundamentals_source TEXT,        -- yfinance | edgar
  cik BIGINT,                      -- SEC registrant id, when the ticker is on EDGAR's list
  edgar_filer BOOLEAN,             -- files 10-K with us-gaap facts (sample eligibility)
  first_price DATE,
  last_price DATE,
  fetched_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vi.prices (
  ticker TEXT NOT NULL,
  date DATE NOT NULL,
  open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
  adj_close DOUBLE,
  volume BIGINT,
  PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS vi.statements (
  ticker TEXT NOT NULL,
  period_end DATE NOT NULL,
  kind TEXT NOT NULL,              -- income | balance | cashflow
  freq TEXT NOT NULL,              -- annual (quarterly deferred)
  line_item TEXT NOT NULL,
  value DOUBLE,
  filed_at DATE,                   -- real filing date when known (EDGAR, deferred)
  available_from DATE NOT NULL,    -- filed_at, else period_end + annual_lag_days
  source TEXT NOT NULL,
  PRIMARY KEY (ticker, period_end, kind, freq, line_item)
);

-- Point-in-time views. Every read the agent (later) or the app makes for a
-- video passes a t0 here; nothing dated after it can come back.
CREATE OR REPLACE MACRO vi.prices_as_of(tk, t0) AS TABLE
  SELECT * FROM vi.prices WHERE ticker = tk AND date <= t0;
CREATE OR REPLACE MACRO vi.statements_as_of(tk, t0) AS TABLE
  SELECT * FROM vi.statements WHERE ticker = tk AND available_from <= t0;

-- One row per (ticker, fiscal year). yfinance's oldest column is usually a stub
-- of ~20 line items with no revenue or net income; a year counts as complete
-- only when the headline items are present.
-- Grouped by fiscal-year label (year of period end) rather than the exact date:
-- EDGAR and yfinance can disagree on the day (Apple: 2025-09-27 vs 2025-09-30)
-- and they are the same fiscal year.
CREATE OR REPLACE VIEW vi.fiscal_years AS
  SELECT ticker, year(period_end) AS fy, max(period_end) AS period_end,
         min(available_from) AS available_from, count(*) AS n_items,
         bool_or(source = 'edgar') AS from_edgar,
         bool_or(line_item = 'Total Revenue') AND bool_or(line_item = 'Total Assets') AS complete
  FROM vi.statements WHERE freq = 'annual' GROUP BY ticker, year(period_end);

-- Milestone 2. One golden eval per sampled video: the author's call, his
-- valuation inputs, the ranked reasons (JSON, each with a data check) and the
-- critic's verdict. `position` is derived from `stance_detail` by rule C
-- (BUY / HOLD / SELL); the binary and hurdle views are derived at read time.
DROP TABLE IF EXISTS vi.calls;  -- the empty M1 stub; superseded by vi.evals
CREATE TABLE IF NOT EXISTS vi.evals (
  video_id TEXT PRIMARY KEY,
  ticker TEXT NOT NULL,
  t0 DATE NOT NULL,
  position TEXT NOT NULL,          -- BUY | HOLD | SELL   (rule C, derived)
  stance_detail TEXT NOT NULL,     -- absolute_buy | relative_buy | fair_hold | avoid | too_hard | short
  personal_action TEXT,            -- buying | holding | watching | none | short
  expected_return_pct DOUBLE,
  horizon_years DOUBLE,
  conviction TEXT,                 -- low | medium | high
  rule_sensitive BOOLEAN,          -- the hurdle cut (B) disagrees with rule C
  title_says_buy BOOLEAN,          -- title/transcript mismatch flag; never an input
  headline_quote TEXT,
  valuation JSON,                  -- method, base metric, scenarios, stated IVs
  iv_weighted_stated DOUBLE,
  iv_recomputed JSON,              -- valuation.py on the extracted inputs
  price_mentioned DOUBLE,
  price_at_t0 DOUBLE,
  reasons JSON,                    -- [{rank, direction, category, claim, quote, chunk_id, start_s, feeds, data_check}]
  external_facts JSON,
  critic JSON,                     -- {faithful, position_agrees, own_stance_detail, notes}
  checks JSON,                     -- {faithful_share, reproducible_share, price_check, iv_within_band}
  extractor_version TEXT,
  model TEXT,
  session_id TEXT,
  transcript_sha256 TEXT,
  split TEXT,                      -- train | test | holdout
  curation_status TEXT DEFAULT 'auto',  -- auto | reviewed | rejected
  review_note TEXT,
  reviewed_at TIMESTAMP,
  extracted_at TIMESTAMP
);

-- Forward returns vs the benchmark at T0 + h months, and the verdict on the call.
CREATE TABLE IF NOT EXISTS vi.validations (
  video_id TEXT NOT NULL,
  horizon_m INTEGER NOT NULL,
  t0 DATE,
  t1 DATE,
  ret DOUBLE,
  bench_ret DOUBLE,
  excess DOUBLE,                   -- ret - bench_ret, in fraction (0.05 = 5 pp)
  verdict TEXT,                    -- correct | wrong | indeterminate   (D14 bands)
  verdict_hold_alt TEXT,           -- HOLD scored as "did not lag by > 5 pp"; same as verdict otherwise
  iv_hit BOOLEAN,                  -- price touched the stated IV within the horizon
  PRIMARY KEY (video_id, horizon_m)
);

-- Daily risk-free series from FRED (DGS10, DGS3MO), so "treasuries at 4 %" reasons ground.
CREATE TABLE IF NOT EXISTS vi.rates (
  series TEXT NOT NULL,
  date DATE NOT NULL,
  value DOUBLE,
  PRIMARY KEY (series, date)
);
CREATE OR REPLACE MACRO vi.rates_as_of(series_id, t0) AS TABLE
  SELECT * FROM vi.rates WHERE series = series_id AND date <= t0;
-- D15: train/test are stamped per eval (seeded, within each window year); holdout is the
-- state at a horizon whose outcome is not yet in vi.prices, so it depends on h.
CREATE OR REPLACE MACRO vi.split_at(h) AS TABLE
  SELECT e.video_id, e.split, CASE WHEN val.video_id IS NULL THEN 'holdout' ELSE e.split END AS split_at
  FROM vi.evals e LEFT JOIN vi.validations val ON val.video_id = e.video_id AND val.horizon_m = h;
