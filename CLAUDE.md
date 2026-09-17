# CLAUDE.md — value-invest-agent

> Read [`AGENTS.md`](./AGENTS.md) first: what this is, the decisions, the layout,
> the pipeline. The plan of record is `ai_specs/s00_project_plan.md`. This file
> is a pointer plus the rules that bite.

## Quick reference

- `uv sync` · `uv run vi --help` · `uv run pytest -q` · `uv run ruff check . && uv run ruff format .` · `uv run mypy`
- Transcripts live in the sibling `../transcript-rag-agent` (Chroma at `.yt-agent/chroma`, API on :8000). Read its `readme.md` and `AGENTS.md` before touching ingestion.

## Rules

- **Point-in-time is the invariant.** Every agent tool reads through `vi.as_of`
  bound to the call's `t0`. Never add a data path that bypasses it. A test must
  fail if a row with `date > t0` or `filed_at > t0` can reach the agent.
- **One LLM chokepoint** (`src/value_invest/llm.py`, ConvFinQA pattern): the only
  place a model is constructed; owns the demo gate and retry/timeout. Importing
  any module must never require an API key.
- **Never write to transcript·lab's Chroma from this repo.** Ingest through its
  CLI or `/api/index/queue`; read back by `video_id` / chunk id.
- **Derived state is rebuildable, not committed.** `.vi/` caches and
  `data/value_invest.duckdb` are gitignored; only a small demo snapshot ships.
- **Splits are by video date, never random.** Holdout ≥ 2025-07 is sealed.
- **Every headline number carries its n and horizon**, reported per year and per
  region — never an average that hides a failing segment.
- Use `uv` for all dependency operations; Ruff for format/lint; mypy strict.
- Never hardcode API keys; keys come from `~/.env` or `./.env`.
- Never add `.lavish/` to `.gitignore`.
