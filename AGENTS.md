# AGENTS.md — value-invest-agent

## What this is

An evaluation-first project with two loops over one golden set built from a
value-investing YouTube channel (@Value-Investing, ≈1,000 videos in the last four
years):

1. **Reproduction loop** — an analyst agent, given only prices and financial
   statements available on the video date (T0), produces a call (stance,
   intrinsic value, thesis). Scored against the transcript's call.
2. **Validation loop** — every call (channel's and agent's) is scored against the
   forward return at T0 + 6 / 12 / 24 months relative to a benchmark.

## Decisions (see `ai_specs/s00_project_plan.md` for the reasoning)

- **Storage:** transcripts and chunks stay in transcript·lab's Chroma
  (channel-scoped by `channel_id`); structured data lives in
  `data/value_invest.duckdb`, schema `vi`. Foreign keys are transcript·lab's own
  ids. Two stores, one-directional dependency, `vi.videos` rebuilt from the
  corpus API.
- **Video filter:** a title classifier (LLM, structured output) that resolves
  company → ticker, not a ticker regex — only ~1 in 4 titles carry a ticker.
  Seed eval: `data/samples/titles_2026-09.json` (40 hand-labelled titles).
- **Fundamentals:** yfinance for prices everywhere; yfinance + SEC EDGAR
  `companyfacts` (filing dates) for US names; non-US flagged `shallow`.
- **Agent learning:** prompt-optimisation loop (teacher + gate) first, retrieval
  few-shot as an ablation, no fine-tune in the first milestone.
- **Leakage controls:** date-based splits, a no-tools baseline as the leakage
  floor, sealed holdout ≥ 2025-07.

## Layout (target)

```text
src/value_invest/
  config.py        settings + dotenv
  llm.py           the single LLM chokepoint
  db.py            DuckDB connection, schema init, as_of binding
  catalog/         Supadata listing + dating (shares transcript-lab's cache format)
  classify/        title → kind + tickers (structured LLM), seed eval
  ingest/          drives transcript-lab ingestion, reads corpus back
  golden/          GoldenCall schema, extractor, cache, curation, splits
  market/          yfinance + EDGAR loaders → parquet → DuckDB
  agent/           tools over vi.as_of, AnalystReport, baselines
  scoring/         stance/IV/thesis metrics, judge
  validate/        forward returns, verdicts, scoreboard
  loop/            teacher, gate, prompt versions (agents/vN/system.md)
  serving/         FastAPI app, demo mode
  cli.py           `vi` Typer app
frontend/          Vite + React walkthrough (transcript-lab design tokens)
data/
  schema.sql       the vi schema
  samples/         committed seeds (titles)
  snapshot/        small demo DuckDB snapshot
ai_specs/          dated specs; s00 is the plan of record
.lavish/           review artifacts (sNN_*.html) — never gitignored
tests/
```

## Pipeline stages

S1 catalog → S2 classify → S3 ingest (in transcript·lab) → S4 extract → S5 market
→ S6 agent + validate → S7 app. Each stage is a `vi` subcommand with an
idempotent output table, so any stage can be re-run without re-fetching upstream.

## Working guidelines

- Keep changes small and reviewable; one spec per slice under `ai_specs/`.
- Mock Supadata, yfinance, EDGAR and LLM calls in tests; commit small fixtures.
- Prompts are versioned files, never edited by hand once a run has scored them.
- Document new commands and env vars in `README.md` and `.env.example`.
