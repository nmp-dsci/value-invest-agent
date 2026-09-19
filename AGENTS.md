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
- **Video filter:** a title classifier (Agent SDK, structured output) that
  resolves company → ticker, not a ticker regex — only ~1 in 4 titles carry a
  ticker. Seed eval: `data/samples/titles_2026-09.json` (40 hand-labelled titles).
- **Sample:** single-stock videos only, 10 per year × 4 years = 40 as the base
  (`vi sample --per-year 10 --seed 42`, spread across quarters). Expand later by
  raising `--per-year`; existing picks are stable under the seed.
- **Runtime:** every model call is a Claude Agent SDK session billed to the
  subscription (`BILLING=subscription`, `CLAUDE_CODE_OAUTH_TOKEN`), through the
  single chokepoint `llm.py` — ConvFinQA's `evalloop/sdk.py` / DABStep's
  `agent/llm.py` pattern. No Pydantic AI, no DeepSeek, no `ANTHROPIC_API_KEY`.
- **Agent shape:** DABStep's — one stateful Python tool (`execute_python`, an
  in-process SDK MCP server whose namespace preloads `pd` and `helper`), a
  version folder `agents/vN/{system.md, helper.py, agent.yaml}`; `agent.yaml`
  frozen. The sandbox opens DuckDB read-only with `vi.t0` bound.
- **Fundamentals:** yfinance for prices everywhere; yfinance + SEC EDGAR
  `companyfacts` (filing dates) for US names; non-US flagged `shallow`.
- **Agent learning:** the DABStep error loop — one optimiser session reads the
  wrong traces and the ledger, writes `agents/v(N+1)/{system.md, helper.py}`
  (system prompt or Python functions the sandbox exposes — nothing else), a
  challenger run on test, a McNemar gate on paired calls, a ledger entry.
  Retrieval few-shot is an ablation; no fine-tune in the first milestone.
- **Leakage controls:** date-based splits, a no-tools baseline as the leakage
  floor, sealed holdout ≥ 2025-07.

## Layout

```text
src/value_invest/
  config.py        Settings; reads ./.env then ~/.env with dotenv_values, never exports secrets
  llm.py           the Agent SDK chokepoint: billing guard, subscription_env, run_structured
  db.py            DuckDB connection + data/schema.sql (vi.*_as_of macros)
  cli.py           `vi` (typer): db · catalog · classify · sample · refine-dates · ingest · market · coverage · serve
  catalog/         supadata.py (paced, cached client) · ytdlp.py (channel tab + per-video) · build.py
  classify/        models.py (TitleLabel) · run.py (batched SDK calls, seed eval)
  sample.py        seeded, quarter-stratified draw that extends without reshuffling
  ingest/          run.py (index-rag in ../transcript-rag-agent per video) · corpus.py (read-only Chroma)
  golden/          M2: GoldenCall schema, extractor, curation, splits
  market/          yahoo.py (prices + annual statements → parquet) · load.py · coverage.py
  agent/           session.py (ClaudeSDKClient), tools/python_executor.py, versions.py, AnalystReport, baselines
  scoring/         stance/IV/thesis metrics, judge
  validate/        forward returns, verdicts, scoreboard
  loop/            optimiser session, McNemar gate, ledger
agents/vN/         system.md · helper.py · agent.yaml (frozen) · diagnosis.json
  serving/         app.py — FastAPI: /api/health /funnel /videos /videos/{id} /market/coverage /sql /sql/catalog; serves frontend/dist
                   sql.py — the SQL viewer's executor: read-only connection, single SELECT/WITH validated, row cap, interrupt timeout
frontend/          Vite + React 19; src/tokens.css copied from transcript-lab; views Corpus · Video · Market · Sql (CodeMirror) (+ M2 stubs)
data/
  schema.sql       the vi schema
  samples/         titles_2026-09.json (40 titles) · titles_2026-09_labels.json (hand labels) · classifier_seed_eval.json
  golden/          seed_labels.json (hand labels) · stated_ivs.json (his on-camera IVs) · evals/<video_id>.json (cache) · seed_eval_vN.json · kappa.json · method_summary.json
extractors/v0/     system.md (the extractor prompt) · version.yaml (frozen: model, effort, critic)
.vi/               caches (gitignored): supadata/ ytdlp/ market/<ticker>/*.parquet
ai_specs/          dated specs; s00 is the plan of record
.lavish/           review artifacts (sNN_*.html) — never gitignored
tests/
```

## Pipeline stages

S1 catalog → S2 classify → S3 ingest (in transcript·lab) → S2 market/edgar/rates
→ S4 extract (golden evals) → S5 validate → app. Each stage is a `vi` subcommand
with an idempotent output table, so any stage can be re-run without re-fetching
upstream. M2 (`ai_specs/s02_m2_golden_extraction.md`): `vi extract` runs
extract (Sonnet) · ground (python, as-of only) · critic (Opus) · checkpoint;
`vi golden {eval-seed,kappa,summary}` scores a version; `vi validate` writes the
forward-return verdicts. Extractor prompts live in `extractors/vN/` and are the
only surface a later optimiser may edit; `version.yaml` is frozen per version.

## Working guidelines

- Keep changes small and reviewable; one spec per slice under `ai_specs/`.
- Mock Supadata, yfinance, EDGAR and LLM calls in tests; commit small fixtures.
- Prompts are versioned files, never edited by hand once a run has scored them.
- Document new commands and env vars in `README.md` and `.env.example`.
