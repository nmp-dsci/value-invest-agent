# Spec: S00 Project plan — value·invest agent

Status: ready (rev 4 — M1 delivered; M2 detailed in s02_m2_golden_extraction.md)
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

Estimated funnel: 2,072 → ≈1,000 in window → ≈500 single-stock → **40 sampled**
(10 per year × 4, seeded, spread across quarters; `vi sample --per-year 10`).
S1 replaces the stage estimates with counts; the 40 is a decision, not an estimate.

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

Runtime (decided, rev 2): **every model call runs on the Claude Agent SDK billed
to the subscription** — ConvFinQA's `evalloop/sdk.py` / DABStep's `agent/llm.py`
pattern: `BILLING=subscription`, `CLAUDE_CODE_OAUTH_TOKEN`, the guard blanks
`ANTHROPIC_API_KEY` and refuses if both are set. `llm.py` is the only place a
`ClaudeSDKClient` is constructed. No Pydantic AI, no DeepSeek.

Agent shape (decided, rev 2): **DABStep's** — one stateful Python tool
(`execute_python`, in-process SDK MCP server, namespace preloads `pd` and
`helper`), a version folder `agents/vN/{system.md, helper.py, agent.yaml}` with
`agent.yaml` frozen. The optimiser may edit only `system.md` and `helper.py` —
the Python functions the sandbox exposes for pulling and working the data.

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
| S2 classify + sample | title (+description) → kind, tickers[+exchange], confidence; seed eval on 40 labelled titles, target ≥ 95 % on kind; then `vi sample --per-year 10 --seed 42` sets `vi.videos.in_sample` | Agent SDK ≈1,000 |
| S3 ingest | sampled videos only → transcript·lab `/api/index/queue` (fallback: `bulk-index channel --since`, 25× the calls) | Supadata 40 |
| S4 extract | raw transcript → `GoldenCall`, Agent SDK `run_structured`, cached by (video_id, transcript hash, extractor_version); price-mention cross-check vs close at T0 | Agent SDK 40 |
| S5 market | daily OHLCV from 2018 + statements per sampled ticker; benchmarks SPY + local index; parquet → DuckDB | yfinance ≤ 40 tickers, EDGAR for US |
| S6 agent + validate | predictions per call; validations per (call, horizon) | Agent SDK 40 per run |
| S7 app | FastAPI + React walkthrough, demo snapshot | — |

**Point-in-time rule:** prices ≤ T0; statements on `filed_at` ≤ T0 (not
period_end). Yahoo does not expose filing dates → EDGAR for US names; otherwise
assume period_end + 45 (quarterly) / 90 (annual) days.

## Golden set

- `GoldenCall`: ticker, exchange, stance (5-way), stance_strength, conditional_on,
  intrinsic_value (+method), price_mentioned, horizon_years, thesis[], risks[],
  verifiable_claims[], evidence[] (chunk ids + timestamps), is_primary.
- Curation as in transcript·lab `docs/golden-set-curation.md`: at 40 calls every
  one is hand-reviewed (`curation_status=reviewed`); rows added when the sample
  grows arrive as `auto` and are reported separately until reviewed.
- Inter-extractor κ on stance over the reviewed core; κ < 0.7 means the taxonomy
  is wrong. 3-way collapse (bullish/neutral/bearish) is the fallback headline.
- Splits: superseded by D15 (seeded within-year train/test, per-horizon holdout) —
  see `ai_specs/s02_m2_golden_extraction.md`. Gate is McNemar on paired calls.

## Market data

| Need | yfinance | Fallback |
|---|---|---|
| daily OHLCV, any exchange | yes (`history(period="max")`, suffixes `.PA`, `.DE`, `.HK`) | — |
| quarterly statements | ≈ last 5 quarters only | EDGAR `companyfacts` (US) / paid API |
| annual statements | ≈ last 4 years (today FY2022–25) | EDGAR back to 2009 (US) |
| **annual only** — last FY with year-end + 90 d ≤ T0 | covers sampled videos from 2023-04 on (≈30 / 40); first-year videos need FY2021, which Yahoo no longer returns | EDGAR for first-year US names; non-US flagged shallow |
| filing dates | not exposed | EDGAR `filed`; else period_end + 45/90 d |

Option 1b, annual-only: drop quarterlies and give the agent the last annual
report published before T0 — the simplest as-of rule, and a value investor
reasons in fiscal years anyway. Viable first milestone alone; EDGAR fills the
first-year gap for US names.

Recommended: yfinance + EDGAR for US names; non-US flagged
`fundamentals_depth=shallow`. Paid API (FMP/EOD/Polygon) only if non-US names
dominate after S2.

## Analyst agent

- One tool: `execute_python` (stateful sandbox). The sandbox opens DuckDB
  read-only with `vi.t0` bound, so every helper — and any raw SQL the agent
  writes — reads through `vi.as_of`. A test asserts no row with date > t0 leaks.
- `agents/vN/helper.py`: `price_history(window)`, `statement(kind, freq, n)`,
  `ratios()`, `peer_snapshot(peers)`, `prior_calls()` (earlier calls on the name
  via transcript·lab RAG, opt-in). v0 is thin loaders; later versions are
  distilled from failures by the optimiser.
- `agents/vN/agent.yaml` (frozen): model `claude-sonnet-5`, effort, turn budget.
- Output `AnalystReport` = GoldenCall minus evidence, plus confidence + markdown,
  returned as JSON on the final turn.
- Learning (decided): the DABStep error loop — one optimiser session (Opus)
  reads every wrong trace + the ledger → writes `agents/v(N+1)/{system.md,
  helper.py}` → challenger run on test → McNemar gate → ledger. Retrieval
  few-shot is an ablation; fine-tune is a non-goal for milestone 1.
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

## Delivery (rev 3 — data first, review, then decide)

Milestone 1 · data + app
- S0 repo + scaffold — done 2026-09-17.
- S1 transcripts: `llm.py`, `vi catalog`, `vi classify` (seed eval), `vi sample
  --per-year 10`, `vi ingest --sample` → 40 transcripts in transcript·lab.
- S2 market: yfinance daily prices + **annual** statements per sampled ticker,
  `vi.as_of` with the annual-only rule (year-end + 90 d ≤ T0), coverage report,
  leakage test. EDGAR deferred.
- S3 app: Corpus · Video (transcript beside price chart at T0 and as-of annual
  statements) · Market (coverage). Local only.

Milestone 2 · golden evals + validation (see `ai_specs/s02_m2_golden_extraction.md`)
- S4 golden extraction → `vi.evals` (BUY / HOLD / SELL, IV inputs, 3–5 reasons with
  data checks), critic κ, seed checkpoint; S4.4 grows the sample to 20 / yr × 6 = 120.
- S5 Golden Evals tab: forward-return validation on top (moved here from M3),
  every eval below, review control; Video tab shows the eval. **Review checkpoint:
  does the golden set make sense, and were the calls any good?**

Deferred until the M2 review passes: forward-return validator + scoreboard,
analyst agent v0 + baselines, the error loop, EDGAR / quarterlies / sample
expansion, demo deploy + CI eval gate.

## Risks

- **High:** model leakage of future knowledge (controls: no-tools baseline, date
  splits, sealed holdout — report, don't hide).
- **High:** fundamentals depth for 2022–24 and non-US videos.
- **Med:** hedged stance (κ decides; 3-way fallback).
- **Low:** Supadata budget (≈1,050 metadata + 40 transcripts, all cached).
- **Med:** small n — 40 calls, 10 per year; 24 m verdicts for ≈20. Every number
  carries its n; the gate is paired; `--per-year` is the knob to grow it.
- **Med:** two stores drift (`vi.videos` rebuilt from corpus API; CI count check).
- **Low:** ticker resolution (price-mention cross-check + review queue).

## Decisions

- D1 storage: **assumed B** (Chroma for text + DuckDB `vi`) — S1 builds on it unless overridden.
- D2 fundamentals: **decided for M1** — yfinance annual-only (1b); EDGAR/quarterlies deferred.
- D3 scope: **decided** — single-stock only, 10 per year × 4 = 40 base sample, expand later.
- D5 transcripts: **decided** — Supadata topped up; ingest via transcript·lab at one credit per video (transcript-rag-agent #20).
- D6 repeat tickers: **decided** — keep repeats across years; distinct within a year only.
- D7 fundamentals depth: **decided** — SEC EDGAR now; sample restricted to US 10-K filers (`VI_SAMPLE_EDGAR_ONLY=1`).
- D4 learning: **decided** — Claude Agent SDK on subscription; DABStep agent
  shape (Python sandbox + `system.md`/`helper.py` versions); optimiser edits
  only those two files; McNemar gate.
- D8–D14 (M2): recorded in `ai_specs/s02_m2_golden_extraction.md` — 3-way
  position, TTM gap recorded, seed v0 = 14 read videos, FRED rates in, 20 / yr ×
  6 years, US = 10-K filer, HOLD band ±10 pp.

## Acceptance criteria for this spec

- Repo `nmp-dsci/value-invest-agent` public, scaffold committed, this spec and
  the Lavish page in place.
- Decisions D1–D4 recorded here once answered; open questions removed.
