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
CREATE OR REPLACE VIEW vi.fiscal_years AS
  SELECT ticker, period_end, min(available_from) AS available_from, count(*) AS n_items,
         bool_or(line_item = 'Total Revenue') AND bool_or(line_item = 'Total Assets') AS complete
  FROM vi.statements WHERE freq = 'annual' GROUP BY ticker, period_end;

-- Milestone 2 tables, created now so the app's stub tabs have something to query.
CREATE TABLE IF NOT EXISTS vi.calls (
  call_id TEXT PRIMARY KEY,
  video_id TEXT,
  ticker TEXT NOT NULL,
  exchange TEXT,
  t0 DATE NOT NULL,
  stance TEXT,
  stance_strength TEXT,
  conditional_on TEXT,
  intrinsic_value DOUBLE,
  intrinsic_value_method TEXT,
  price_mentioned DOUBLE,
  price_at_t0 DOUBLE,
  horizon_years DOUBLE,
  thesis JSON,
  risks JSON,
  verifiable_claims JSON,
  evidence JSON,
  is_primary BOOLEAN DEFAULT TRUE,
  extractor_version TEXT,
  curation_status TEXT DEFAULT 'auto',
  extracted_at TIMESTAMP
);
