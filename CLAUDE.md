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
- **One LLM chokepoint** (`src/value_invest/llm.py`): the only place a
  `ClaudeSDKClient` is constructed; owns the billing guard, the demo gate and
  effort. Importing any module must never require a key or token.
- **Billing.** Dev runs use the subscription: `BILLING=subscription` and no
  `ANTHROPIC_API_KEY`; `llm.py` refuses to start otherwise. The demo image has
  `DEMO_MODE=1` baked in and cannot call a model.
- **The optimiser may edit two files** (`agents/vN/system.md`, `helper.py`).
  "Improve the agent" means run the loop, not a hand edit; `agent.yaml` is frozen.
- **The sample is 20 single-stock videos per window year over 6 years (120; D12).**
  Expand with `vi sample --per-year N`; the sampler is sticky; never hand-pick
  videos into the sample. Eligibility is "has SEC financial reports with filing
  dates" (D13), not nationality.
- **Position is BUY / HOLD / SELL derived from the 6-way `stance_detail` (D8).**
  The extractor never outputs a position and never sees the title as evidence;
  the transcript is the source of truth. Binary (A) and hurdle (B) views are
  derived at read time, never re-extracted.
- **Grounding is Python, not the model.** `golden/ground.py` fills every
  reason's `data_check` from `vi.statements_as_of` / prices / `vi.rates`; the
  extractor never sees market data. Change grounding → `vi extract --reground`.
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
