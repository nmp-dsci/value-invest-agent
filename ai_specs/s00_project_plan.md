# Spec: S00 Project plan — value·invest agent

Status: draft
Date: 2026-09-17
Review page: `.lavish/s00_value-invest-agent-plan.html` (architecture drawings live there)

## Summary

Build an evaluation-first system around the YouTube channel
*Value Investing with Sven Carlin, Ph.D.* (`@Value-Investing`, channel id
`UCrTTBSUr0zhPU56UQljag5A`):

1. Turn every stock-analysis video of the last four years into a **golden call**
   (ticker, T0 = video date, stance, intrinsic value, thesis, risks, evidence).
2. Build an **analyst agent** that, given only prices and financial statements
   available at T0, produces the same kind of call, and score it against the
   golden call (reproduction loop).
3. **Validate** both the channel's and the agent's calls against the forward
   price at T0 + 6 / 12 / 24 months vs a benchmark (validation loop), and
   fact-check the transcript's verifiable claims against as-of data.
4. Ship an **app** that walks every video from transcript → golden call → agent
   call → verdict.

## What Supadata says about the channel (checked 2026-09-17)

- `channel/videos` returns **2,072 ids**, ids only, newest first (channel meta reports 2,400).
- Dates come from `metadata` per video (`createdAt`, day precision). Id #1000 is
  a 2022 video → **≈1,000 videos** since 2022-09-17.
- 40 most recent titles: ≈20 single-stock, ≈10 multi-stock, ≈10 macro/general.
  Only **9 / 40 carry an explicit ticker**; most name the company ("LVMH Stock…",
  "Nike Stock…"). Many names are non-US (LVMH, Vonovia, Tencent, Xiaomi, Prosus).
- Transcripts state a conclusion explicitly but hedged/conditional, often relative
  and with a long horizon.

Estimated funnel: 2,072 → ≈1,000 in window → ≈750 stock-analysis (≈500 single,
≈250 multi) → ≈900 golden calls. S1 replaces the estimates with counts.

## Architecture

Two repos, one corpus:

- **transcript·lab** (`../transcript-rag-agent`, reused as-is): Supadata
  discovery + disk cache (`src/transcripts/discovery.py`), transcript fetch,
  chunking, MiniLM embeddings, Chroma collections `raw_transcripts` /
  `transcript_chunks` (every chunk carries `channel_id`, `title`,
  `upload_date`), `bulk-index channel --since --until`, API `/api/corpus`,
  `/api/corpus/{video_id}/chunks`, `/api/index/queue`.
- **value-invest-agent** (this repo): catalog + title classifier, golden
  extraction, market loaders, `vi.as_of` point-in-time view, analyst agent with
  tools, scorer + judge, forward-return validator, DuckDB schema `vi`,
  improvement loop, app.

This repo never writes to transcript·lab's Chroma. It triggers ingestion (CLI
or queue API) and reads back by `video_id` / `chunk:<video_id>:<index>`.

Patterns reused: ConvFinQA's single LLM chokepoint (`llm.py`), Pydantic AI stage
agents, MLflow + champion/challenger gate, keyless demo mode; DABStep/tau2's
teacher + gate prompt loop.

## Storage decision

Chroma is a vector store — no joins, no time series — so:

- **B (recommended):** transcripts + chunks in transcript·lab's Chroma
  (channel-scoped); structured data in `data/value_invest.duckdb`, schema `vi`.
  One file, SQL window functions, no new service, transcript·lab untouched.
- A (everything as Chroma metadata): rejected.
- C (shared Postgres schema `vi`): only if a third project needs the tables.

### Schema `vi` (data/schema.sql)

- `vi.videos(video_id PK = Chroma id, title, published_at, duration_s, kind single|multi|macro|other, classifier_version, reviewed_by, transcript_status)`
- `vi.title_labels(video_id, kind, tickers[], source llm|human, confidence)`
- `vi.tickers(ticker PK, name, exchange, currency, benchmark, cik)`
- `vi.calls(call_id PK, video_id FK, ticker, exchange, t0, stance buy|hold|sell|watch|avoid, stance_strength, conditional_on, intrinsic_value, price_at_t0, horizon_years, thesis JSON, risks JSON, verifiable_claims JSON, evidence_chunk_ids JSON, is_primary, extractor_version, curation_status auto|reviewed|rejected)`
- `vi.prices(ticker, date PK, open, high, low, close, adj_close, volume)`
- `vi.statements(ticker, period_end, filed_at, kind income|balance|cashflow, freq, line_item, value, source)`
- `vi.agent_runs(run_id PK, started_at, prompt_version, model, split, mlflow_run_id, n_calls, cost, gate_verdict)`
- `vi.predictions(run_id FK, call_id FK, stance, intrinsic_value, confidence, report_md, tool_trace_json, stance_match, iv_within_band, thesis_overlap)`
- `vi.validations(call_id FK, horizon_m 6|12|24, ret, bench_ret, excess_ret, status, verdict_channel, verdict_agent, run_id)`
- `vi.as_of` view: statements with `filed_at <= t0` (t0 bound once per run).

Everything below `vi.videos` is derived and rebuildable from three caches
(Supadata metadata, market parquet, LLM extraction cache).

## Pipeline

| Stage | What | External calls |
|---|---|---|
| S1 catalog | list ids, date newest→oldest until `createdAt < 2022-09-17` | Supadata ≈1,050 |
| S2 classify | title (+description) → kind, tickers[+exchange], confidence; seed eval on 40 labelled titles, target ≥ 95 % on kind | LLM ≈1,000 |
| S3 ingest | only `single`/`multi` → transcript·lab `/api/index/queue` (fallback: `bulk-index channel --since`) | Supadata ≈750 |
| S4 extract | raw transcript → `GoldenCall[]`, cached by (video_id, transcript hash, extractor_version); price-mention cross-check vs close at T0 | LLM ≈750 |
| S5 market | daily OHLCV from 2018 + statements per ticker; benchmarks SPY + local index; parquet → DuckDB | yfinance ≈400 tickers, EDGAR for US |
| S6 agent + validate | predictions per call; validations per (call, horizon) | LLM ≈900 per run |
| S7 app | FastAPI + React walkthrough, demo snapshot | — |

**Point-in-time rule:** prices ≤ T0; statements on `filed_at` ≤ T0 (not
period_end). Yahoo does not expose filing dates → EDGAR for US names; otherwise
assume period_end + 45 (quarterly) / 90 (annual) days.

## Golden set

- `GoldenCall`: ticker, exchange, stance (5-way), stance_strength, conditional_on,
  intrinsic_value (+method), price_mentioned, horizon_years, thesis[], risks[],
  verifiable_claims[], evidence[] (chunk ids + timestamps), is_primary.
- Curation as in transcript·lab `docs/golden-set-curation.md`: a hand-reviewed
  core of 100 calls stratified by stance and year (`curation_status=reviewed`);
  the rest `auto`, reported separately.
- Inter-extractor κ on stance over the reviewed core; κ < 0.7 means the taxonomy
  is wrong. 3-way collapse (bullish/neutral/bearish) is the fallback headline.
- Splits by video date: train ≤ 2024-06, test 2024-07 → 2025-06, holdout ≥ 2025-07 (sealed).

## Market data

| Need | yfinance | Fallback |
|---|---|---|
| daily OHLCV, any exchange | yes (`history(period="max")`, suffixes `.PA`, `.DE`, `.HK`) | — |
| quarterly statements | ≈ last 5 quarters only | EDGAR `companyfacts` (US) / paid API |
| annual statements | ≈ last 4 years | EDGAR back to 2009 (US) |
| filing dates | not exposed | EDGAR `filed`; else period_end + 45/90 d |

Recommended: yfinance + EDGAR for US names; non-US flagged
`fundamentals_depth=shallow`. Paid API (FMP/EOD/Polygon) only if non-US names
dominate after S2.

## Analyst agent

- Tools over `vi.as_of`: `price_history`, `statement`, `ratios`, `peer_snapshot`,
  `prior_calls` (his earlier calls on the name via transcript·lab RAG; opt-in,
  ablated). A test asserts no row with date > t0 can leak.
- Output `AnalystReport` = GoldenCall minus evidence, plus confidence + markdown.
- Runtime: Pydantic AI through `llm.py`; DeepSeek for volume, Claude for the
  reviewed core; demo mode refuses model calls.
- Learning: (a) prompt-optimisation loop first (teacher diagnoses first-wrong
  cases → one prompt version → gate on test, net-positive + McNemar-significant);
  (b) retrieval few-shot from strictly earlier golden calls as an ablation;
  (c) fine-tune is a non-goal for milestone 1.
- Scoring: `stance_match` (5-way and 3-way), `iv_within_band` (±25 %),
  `direction_vs_price`, `thesis_overlap` (independent judge). Headline: 3-way
  stance accuracy on reviewed calls, per year and per region.
- Baselines: majority stance; ratio rule (FCF yield > 6 % and net debt/EBITDA < 2
  → buy); **no-tools LLM** as the leakage floor.

## Validation

For each call and horizon h ∈ {6, 12, 24} with T0 + h ≤ today:
`ret = adj_close(T0+h)/adj_close(T0) − 1`, `excess = ret − bench_ret`.
Verdict: correct if buy and excess > +5 pp, or sell/avoid and excess < −5 pp, or
hold/watch and |excess| ≤ 10 pp; wrong if the opposite beyond the band;
indeterminate otherwise. Bands are run parameters. IV hit rate: did price reach
the stated IV within the horizon. Scoreboard shows channel and agent side by side
with n and horizon on every number; 24 m verdicts exist only for videos before
2024-09.

## App

FastAPI + Vite/React, transcript·lab's design tokens (`frontend/src/theme.css`)
so it can later be embedded as a workbench tab. Tabs: Corpus · Golden calls
(+ review queue) · Walkthrough · Market (coverage) · Agent runs · Scoreboard ·
Fact-check. Read-only demo with a committed DuckDB snapshot; App Runner deploy
as in the siblings.

## Delivery

- S0 repo + scaffold — done 2026-09-17.
- S1 catalog + classifier → real funnel counts, Supadata spend report.
- S2 ingest via transcript·lab → ≈750 transcripts in Chroma.
- S3 golden extraction + reviewed core + κ + splits.
- S4 market data + `vi.as_of` + leakage test + coverage report.
- S5 validator + scoreboard + fact-check.
- S6 agent v1 + baselines + scoring + MLflow; S6b prompt loop.
- S7 app + demo deploy + CI.

## Risks

- **High:** model leakage of future knowledge (controls: no-tools baseline, date
  splits, sealed holdout — report, don't hide).
- **High:** fundamentals depth for 2022–24 and non-US videos.
- **Med:** hedged stance (κ decides; 3-way fallback).
- **Med:** Supadata budget (≈1,800 calls, all cached; spend reported before ingest).
- **Med:** two stores drift (`vi.videos` rebuilt from corpus API; CI count check).
- **Low:** ticker resolution (price-mention cross-check + review queue).

## Open decisions (answer on the review page)

- D1 storage: B recommended.
- D2 fundamentals: yfinance + EDGAR recommended.
- D3 scope: single + multi, last 4 years recommended.
- D4 learning: prompt loop first recommended.

## Acceptance criteria for this spec

- Repo `nmp-dsci/value-invest-agent` public, scaffold committed, this spec and
  the Lavish page in place.
- Decisions D1–D4 recorded here once answered; open questions removed.
