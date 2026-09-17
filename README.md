# value·invest agent

Can an agent learn to make the calls a value investor makes on YouTube — and were
those calls any good?

Four years of [Value Investing with Sven Carlin, Ph.D.](https://www.youtube.com/@Value-Investing)
(≈1,000 videos, ≈750 of them stock analyses) become a **golden set of dated stock
calls** — ticker, stance (buy / hold / sell / watch / avoid), intrinsic value,
thesis, risks — extracted from transcripts. An **analyst agent** that sees only
the daily prices and financial statements available *on the video date* tries to
reproduce each call. A **validator** scores both the channel and the agent
against what the stock did 6, 12 and 24 months later, relative to a benchmark.

> Status: **S0 — plan and scaffold.** The full plan, with architecture drawings,
> the storage schema, the pipeline, risks and open decisions, is
> [`ai_specs/s00_project_plan.md`](ai_specs/s00_project_plan.md); the reviewable
> page is [`.lavish/s00_value-invest-agent-plan.html`](.lavish/s00_value-invest-agent-plan.html).

## How it fits with the sibling projects

- **[transcript-rag-agent](https://github.com/nmp-dsci/transcript-rag-agent)** (transcript·lab)
  owns everything transcript-shaped: Supadata discovery with a disk cache,
  transcript fetch, chunking, embeddings, the Chroma corpus and its API. This
  project asks it to ingest the channel and reads transcripts back by `video_id`
  and `chunk:<video_id>:<index>`. Nothing here writes to its store.
- **[ConvFinQA-agent](https://github.com/nmp-dsci/ConvFinQA-agent)** supplies the
  patterns for the LLM chokepoint (`llm.py`), Pydantic AI stage agents, MLflow
  tracking with a champion/challenger gate, and the keyless demo mode.
- **[DABStep-loop](https://github.com/nmp-dsci/DABStep-loop)** /
  **[tau2-loop](https://github.com/nmp-dsci/tau2-loop)** supply the scored,
  gated prompt-improvement loop the agent learns through.

Everything finance-shaped is new and lives here: the title classifier and ticker
resolution, the golden-call schema and extractor, yfinance / SEC EDGAR loaders,
the point-in-time `vi.as_of` view, the forward-return validator, the DuckDB
schema `vi`, and the walkthrough app.

## Pipeline

| Stage | Command | Writes |
|---|---|---|
| S1 catalog | `uv run vi catalog --channel @Value-Investing --since 2022-09-17` | `vi.videos` |
| S2 classify | `uv run vi classify` | `vi.title_labels` (kind: single / multi / macro / other, tickers) |
| S3 ingest | `uv run vi ingest --kinds single,multi` → transcript·lab `/api/index/queue` | Chroma (transcript·lab) |
| S4 extract | `uv run vi extract` | `vi.calls` (the golden set) |
| S5 market | `uv run vi market` | `vi.prices`, `vi.statements`, benchmarks |
| S6 agent + validate | `uv run vi run-agent --split test --prompt v1` · `uv run vi validate` | `vi.predictions`, `vi.validations` |
| S7 app | `uv run vi serve` | — |

**Point-in-time rule.** The agent never sees anything dated after the video:
prices are cut at T0, statements are filtered on *filing date* ≤ T0. One view
(`vi.as_of`) enforces it and one test asserts nothing leaks.

## Setup

```bash
uv sync
cp .env.example ~/.env          # fill in SUPADATA_API_KEY and ANTHROPIC_API_KEY
uv run vi --help
uv run pytest -q
```

The transcript corpus is expected in a sibling `transcript-rag-agent` checkout
(`TRANSCRIPT_LAB_API`, `TRANSCRIPT_LAB_CHROMA_PATH` in `.env.example`).

## Licence

MIT — see `LICENSE`.
