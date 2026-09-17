# value·invest agent

Can an agent learn to make the calls a value investor makes on YouTube — and were
those calls any good?

Four years of [Value Investing with Sven Carlin, Ph.D.](https://www.youtube.com/@Value-Investing)
(≈1,000 videos, ≈500 of them single-stock analyses; a base sample of **10 per
year, 40 in all**, expandable) become a **golden set of dated stock calls** — ticker, stance (buy / hold / sell / watch / avoid), intrinsic value,
thesis, risks — extracted from transcripts. An **analyst agent** — a Claude Agent SDK
session with one Python-sandbox tool, DABStep-style — that sees only the daily
prices and financial statements available *on the video date* tries to reproduce
each call, and an error loop rewrites its `system.md` / `helper.py` between
gated versions. A **validator** scores both the channel and the agent
against what the stock did 6, 12 and 24 months later, relative to a benchmark.

> Status: **S0 — plan and scaffold.** Next: M1 (transcripts, Yahoo annual data, app) then M2 (golden extraction + eval summary, reviewed in the app) before anything agent-shaped is built. The full plan, with architecture drawings,
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
  Claude Agent SDK on subscription billing (`evalloop/sdk.py`), the single
  chokepoint `llm.py`, MLflow tracking with a champion/challenger gate, and the
  keyless demo mode.
- **[DABStep-loop](https://github.com/nmp-dsci/DABStep-loop)** supplies the agent
  shape: one stateful Python tool, `agents/vN/{system.md, helper.py, agent.yaml}`,
  and the error loop whose optimiser edits only the prompt and the helper
  functions, gated by a McNemar test.

Everything finance-shaped is new and lives here: the title classifier and ticker
resolution, the golden-call schema and extractor, yfinance / SEC EDGAR loaders,
the point-in-time `vi.as_of` view, the forward-return validator, the DuckDB
schema `vi`, and the walkthrough app.

## Pipeline (milestone 1, built)

| Stage | Command | Writes | Source |
|---|---|---|---|
| S1a catalog | `uv run vi catalog` | `vi.videos` (2,071 videos, 1,032 in the 4-year window) | Supadata id list (cached) + yt-dlp channel tab for dates; exact dates merged from the Supadata / yt-dlp per-video caches (`date_source`) |
| S1b classify | `uv run vi classify` · `--eval-seed` | `vi.title_labels` → `vi.videos.kind / primary_ticker` | Claude Agent SDK, 40 titles per call; 95 % kind / 95 % ticker agreement on the 40-title seed |
| S1c sample | `uv run vi sample --per-year 10` | `vi.videos.in_sample / sample_rank` | seeded, quarter-stratified, extends without reshuffling |
| S1a′ refine | `uv run vi refine-dates` | exact `published_at` for sampled videos | per-video yt-dlp |
| S1d ingest | `uv run vi ingest` | transcript·lab's Chroma; `vi.videos.transcript_status` | runs `index-rag` in `../transcript-rag-agent` per sampled video (**Supadata credits**) |
| S2 market | `uv run vi market` · `uv run vi coverage` | `vi.tickers`, `vi.prices`, `vi.statements` (annual) | yfinance; benchmark per exchange |
| S3 app | `uv run vi serve` → http://127.0.0.1:8791 | — | FastAPI over DuckDB + transcript·lab corpus; React in transcript·lab's tokens |

**Point-in-time rule.** `vi.prices_as_of(ticker, t0)` and
`vi.statements_as_of(ticker, t0)` are the only reads the app (and later the
agent) makes for a video; a fiscal year becomes visible at `period_end + 90 d`.
`tests/test_as_of.py` asserts nothing dated after `t0` can come back.

### Data-source notes learned building M1

- **Supadata's plan limit** was exhausted after 144 metadata calls
  (`limit-exceeded`). Dating the channel therefore uses yt-dlp: the channel tab
  gives every video an *approximate* date in one call; per-video extraction
  gives exact dates but YouTube bot-checks it after a few hundred calls, so it
  is reserved for the 40 sampled videos. Transcripts still go through
  transcript·lab → Supadata and need credits.
- **yfinance annual statements** cover ≈ 4–5 fiscal years (today FY2021/22 →
  FY2025/26), so the annual-only as-of rule covers most sampled videos;
  first-window-year videos may see 0–1 fiscal years. The Market tab reports
  this per video.

## Setup

```bash
uv sync
cp .env.example .env            # SUPADATA_API_KEY; BILLING=subscription (the Claude CLI login is the credential)
cd frontend && npm install && npm run build && cd ..
uv run vi --help
uv run pytest -q
```

The transcript corpus is expected in a sibling `transcript-rag-agent` checkout
(`TRANSCRIPT_LAB_API`, `TRANSCRIPT_LAB_CHROMA_PATH` in `.env.example`).

## Licence

MIT — see `LICENSE`.
