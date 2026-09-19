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
| S1d ingest | `uv run vi ingest` | transcript·lab's Chroma; `vi.videos.transcript_status` | runs `index-rag --metadata-json` in `../transcript-rag-agent` per sampled video, passing the cached metadata so each video costs **one** Supadata credit (transcript·lab's default is two: transcript + metadata) |
| S2 market | `uv run vi market` · `uv run vi coverage` | `vi.tickers`, `vi.prices`, `vi.statements` (annual) | yfinance; benchmark per exchange |
| S3 app | `uv run vi serve` → http://127.0.0.1:8791 | — | FastAPI over DuckDB + transcript·lab corpus; React in transcript·lab's tokens. Tabs: Corpus · Video · Market · **SQL** (read-only editor over schema `vi`: catalog, examples, ⌘⏎, history; `POST /api/sql`, single SELECT, ≤ 1000 rows, 20 s) |

**Point-in-time rule.** `vi.prices_as_of(ticker, t0)` and
`vi.statements_as_of(ticker, t0)` are the only reads the app (and later the
agent) makes for a video; a fiscal year becomes visible at `period_end + 90 d`.
`tests/test_as_of.py` asserts nothing dated after `t0` can come back.

## Pipeline (milestone 2, in progress — plan: `ai_specs/s02_m2_golden_extraction.md`)

| Stage | Command | Writes | Notes |
|---|---|---|---|
| S4.0 template | `uv run vi valuation check` | — | `src/value_invest/valuation.py` is the author's intrinsic-value template (two-stage 10-year growth, terminal P/E, 10 % discount, scenario weights); `data/golden/stated_ivs.json` holds the values he states on camera and the check keeps the code within his rounding of them (10 / 10) |
| S4 extract | `uv run vi extract` · `--only ID` · `--force` · `--reground` | `vi.evals`, `data/golden/evals/<video_id>.json` | transcript → `GoldenEvalDraft` (Agent SDK, Sonnet, `extractors/v0/system.md`) → grounding in `vi.statements_as_of` / prices / FRED (python) → critic (Opus: quotes verbatim, independent stance for κ) → checkpoint. Cache keyed on (video, transcript sha, prompt fingerprint); `--reground` rebuilds the data checks with no model call. Position is BUY / HOLD / SELL from the 6-way `stance_detail` (rule C); binary and hurdle views derived |
| S4.3 checkpoint | `uv run vi golden eval-seed` · `kappa` · `summary` | `data/golden/seed_eval_v0.json`, `kappa.json`, `method_summary.json` | seed = `data/golden/seed_labels.json` (36 hand labels, 17 read in full); κ extractor vs critic on the 6-way and 3-way stance; the method summary is the distilled parameter table (discount rate, terminal multiples by growth bucket, probabilities, reason mix) |
| S4.4 window | `VI_SINCE=2020-09-17 VI_SAMPLE_PER_YEAR=20 VI_PRICES_FROM=2015-01-01` then catalog → classify → refine-dates → `vi edgar --check-candidates --recheck` → sample → ingest → market → edgar → extract | +80 videos (20 / yr × 6 = 120) | sticky sampler keeps the first 40; eligibility = SEC filer with annual us-gaap statements (10-K or 20-F/40-F), CIK overrides in `data/edgar_cik_overrides.json` |
| S5 validate | `uv run vi validate` · `uv run vi rates` | `vi.validations`, `vi.rates` | excess return vs the benchmark at T0 + 6 / 12 / 24 m; verdict bands: BUY right if > +5 pp, SELL right if < −5 pp, HOLD right within ±10 pp (D14; "did not lag > 5 pp" kept beside it); `iv_hit` = price touched his stated IV inside the horizon. FRED DGS10 / DGS3MO for the risk-free comparisons |
| S5 app | `uv run vi serve` | — | **Golden Evals** tab: insights on top (per-class hit rates by horizon, per-year train / test / holdout table at the chosen horizon, reproducibility, κ, seed eval, the distilled method), every eval in a table below, row → detail (valuation with recomputed check, reasons with data-check chips and ▶ timestamps, accept / edit / reject → `POST /api/evals/{id}/review`, which also writes the human label into `seed_labels.json`). The **Video** tab shows the same eval panel beside the transcript; ▶ jumps to the cited chunk; the chart carries his IV line and the +6/12/24 m verdict markers |

### M2 results (extractor v2, 120 evals, 2026-09-19)

- Position mix BUY / HOLD / SELL = 22 / 29 / 69; 58 videos state an intrinsic value.
- Seed: position accuracy 88% on the 17 fully-read videos (balanced 0.90), 86% on all 36; reason recall 0.71; quotes verbatim 0.99. Iterations v0 → v1 → v2: 76 % → 82 % → 88 %.
- κ extractor vs critic on the 6-way stance 0.74 (3-way 0.80); the critic agrees on the position in 106 / 120.
- Validation at 12 months (n 100): BUY right 6 / 19, HOLD 8 / 26, SELL 28 / 55; verdicts 42 correct · 51 wrong · 7 indeterminate.
- Splits (D15): train / test stamped per video within each window year (seeded, 30 % test → 84 / 36); holdout is per horizon = outcome not yet in `vi.prices` (10 · 20 · 40 evals at 6 · 12 · 24 m). `SELECT * FROM vi.split_at(12)`; `uv run vi golden splits` re-stamps.
- 597 reasons, 55 % reproducible from data at T0 (statements / prices / derived); the rest rest on consensus, guidance, segments, 13F or judgement.
- Known limits: the quoted-price check passes 25 / 68 (he quotes pre-split prices; `vi.prices.close` is split-adjusted), intrinsic values recompute within ±10 % in 15 / 40 scenarios (he adjusts inputs while talking), 26 evals use a base metric > 15 % from the last annual figure (TTM vs annual, D9).

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
