# Spec: S02 Milestone 2 — golden extraction + Golden Evals tab

Status: ready (rev 1 — all decisions taken in review)
Date: 2026-09-19
Review page: `.lavish/s02_m2-golden-extraction-plan.html` (method figure, schema, pipeline, mocks, decisions)
Branch: `m2-golden`

## Summary

Turn every sampled transcript into a **golden eval**: position BUY / HOLD / SELL,
the author's intrinsic value with its scenario inputs, and the 3–5 ranked reasons
he gives — each reason quoted, anchored to a transcript chunk + timestamp, and
tagged with whether it can be rebuilt from the point-in-time data in DuckDB.
Extraction is a versioned Agent SDK pipeline on the subscription, checkpointed
against a hand-labelled seed. The Golden Evals tab shows validation (his call vs
the stock 6 / 12 / 24 months later, per year and split) on top and every eval in
a table below; the Video tab shows the eval beside the transcript.

## What the transcripts say (14 read in full, 26 at the conclusion)

- His valuation is one reproducible template: base EPS (or DPS / net income),
  growth years 1–5 and 6–10, terminal P/E, 10 % discount rate, three scenarios
  (normal / best / worst) with probabilities → weighted IV vs price → quadrant →
  stance. A 12-line reimplementation reproduces 11 / 11 stated IVs within ±11 %
  (8 within ±6 %). S4.0 pins the exact template from his downloadable sheet.
- The only factual inputs are the base metric and the price; growth, multiple,
  probabilities are judgement. The reasons are the arguments for those judgements.
- Stance vocabulary → 6-way `stance_detail`: absolute_buy · relative_buy ·
  fair_hold · avoid · too_hard · short. Provisional labels on the 40: 9 BUY ·
  7 HOLD · 20 SELL · 4 pending. Titles lie (BLK "Buy… 2x!" is ironic) — the
  transcript is the source of truth; the title is only a mismatch flag.
- Data gaps at T0: he uses TTM EPS (NVDA 6.53 vs annual 4.90); VZ's EDGAR facts
  lack shares/debt (yfinance fallback); consensus, guidance, segment data and 13F
  holdings are external (~⅓ of reasons).

## GoldenEval v1 (`src/value_invest/golden/models.py`)

- call: video_id · ticker · t0 · position BUY|HOLD|SELL (derived, rule C) ·
  stance_detail (6-way) · personal_action · expected_return_pct · horizon_years ·
  conviction · rule_sensitive · headline_quote · title_says_buy
- valuation: method eps_multiple|dividend|fcf|net_income|none · base_metric
  {name, value_stated, quote} · discount_rate · payout_ratio · scenarios[3]
  {name, g_y1_5, g_y6_10, terminal_multiple, probability, iv_stated} ·
  iv_weighted_stated · price_mentioned · what_is_priced_in
- reasons[3–5]: rank · direction for_buy|for_sell · category (valuation, growth,
  capital_allocation, balance_sheet, moat, cyclicality, management, macro_rates,
  competence, sentiment) · claim · quote · chunk_id · start_s · feeds
  (g_y1_5|g_y6_10|terminal|probability|discount|none) · data_check {reproducible
  statements|prices|derived|external|judgement, line_items, value_stated,
  value_as_of, agrees, formula, as_of_period, gap_note}
- provenance: extractor_version · model · session_id · transcript_sha256 ·
  extracted_at · evidence[] · curation_status auto|reviewed|rejected · critic
  {faithful, position_agrees, own_stance, notes} · external_facts_used[] · split

## Pipeline (`vi extract`)

1. locate (python): segments → sentences with chunk ids + seconds; sha256; cache check.
2. extract (Agent SDK, Sonnet 5, `llm.run_structured`): transcript only → GoldenEval draft.
   System prompt = `extractors/vN/system.md` (rule C, taxonomy, template, 2 few-shots).
3. ground (python): per reason resolve line items via a category → formula table,
   pull `vi.statements_as_of` (EDGAR first, yfinance fallback), `vi.prices`,
   `vi.rates` (FRED); recompute scenarios with `valuation.py`; price_mentioned vs
   closes within ±5 trading days; mark reproducible / agrees.
4. critic (Agent SDK, Opus 5): quotes verbatim (fuzzy ≥ 0.9), position follows rule
   C, no invented reason; independent stance_detail → κ.
5. checkpoint: `data/golden/<video_id>.json` keyed by (video_id, transcript_sha256,
   extractor_version); upsert `vi.evals`; seed eval; `kappa.json`;
   `method_summary.json`.

Versions: `extractors/vN/{system.md, rubric.md, version.yaml}`; version.yaml
frozen (model, effort, max_turns). Every model call goes through
`value_invest.llm.run_structured`; port tau2-loop's session-limit wait.

## Checkpoint metrics (`data/golden/seed_eval_vN.json`)

position accuracy (3-class, balanced, per-class recall) · stance κ (6-way, 3-way)
≥ 0.7 · faithfulness ≥ 0.95 · reason recall vs seed · IV fidelity ±10 % ·
price check · reproducibility share (report). A new version ships only if
nothing regresses. Splits stamped on every eval: train 2020/21–2023/24, test
2024/25, holdout 2025/26.

## Validation (moved from M3 into S5)

`vi validate` → `vi.validations(video_id, horizon_m, ret, bench_ret, excess,
verdict, iv_hit)` for h ∈ {6, 12, 24} with T0 + h ≤ last price; benchmark SPY.
Verdict: BUY correct if excess > +5 pp, wrong if < −5 pp; SELL (avoid / too_hard /
short) the mirror; HOLD correct if |excess| ≤ 10 pp (D14), with the "did not lag by
> 5 pp" view reported beside it. Preview on provisional labels at 12 m (n = 27):
BUY 3 ✓ / 2 ✗, HOLD 1 ✓ / 4 ✗, SELL 8 ✓ / 6 ✗; always-SELL baseline 8 / 27.

## App (S5)

- Golden Evals tab (renamed from Golden calls): insights on top — KPIs per class,
  per-year × split × horizon table, notable calls, alternative cuts A / B — evals
  table below with filters; row → detail (valuation with recomputed check, reasons
  with data-check chips and ▶ timestamps, review accept / edit / reject).
- Video tab: the same eval panel beside the transcript; ▶ scrolls to the chunk and
  highlights the quote; chart gains the IV line and T0 + 6 / 12 / 24 m markers.
- API: `GET /api/evals/summary`, `GET /api/evals`, `GET /api/evals/{id}`,
  `POST /api/evals/{id}/review`; `GET /api/videos/{id}` returns the eval.
- `vi.evals` replaces the empty `vi.calls` stub; `vi.validations`, `vi.rates` new.

## Delivery (5½ days + S4.4)

- S4.0 pin the template → `valuation.py` + tests (½ d).
- S4.1 schema + extractor v0 + seed (14 labels) → iterate on the 40 (1 d).
- S4.2 ground + critic + κ + FRED rates loader (1 d).
- S4.3 checkpoint, `vi golden summary`, docs, spec (½ d).
- S4.4 extend the window: `VI_SINCE=2020-09-17`, `VI_SAMPLE_PER_YEAR=20`,
  `prices_from → 2015-01-01`; classify → refine-dates → EDGAR check → sticky sample
  (+80) → ingest (80 Supadata credits, balance check first) → market/edgar →
  extract (1 d). Credit-free steps first; they replace the pool estimates
  (≈ 27 / 40 eligible in 2020/21 / 2021/22) with real counts.
- S5 Golden Evals tab + Video panel + `vi validate` (1½ d) → /no-mistakes, PR,
  walkthrough page s03 = the M2 review checkpoint.

Definition of done: 120 evals in `vi.evals` (40 reviewed, 80 auto) with
validations at every horizon the data allows; κ and seed eval published;
`valuation.py` reproduces the stated IVs; the tab lets you review each eval.

## Decisions

- D8 headline position: **BUY / HOLD / SELL** (rule C); binary A (HOLD → SELL)
  and hurdle B (expected return ≥ 10 %) reported as derived cuts.
- D9 base metric: record annual-vs-TTM gap in M2; EDGAR 10-Q + TTM in M3.
- D10 seed: my 14 read videos seed v0; reviews in the tab become human labels.
- D11 additions: X1 FRED risk-free loader included; X2 optimiser deferred; X3
  all-286 extraction deferred; X4 Video-tab panel included.
- D12 sample: 20 per year × 6 years (2020-09-17 →) = 120; sequenced after the
  extractor works on the 40.
- D13 US = US-listed 10-K filer with us-gaap facts (current `check_filer`).
- D14 HOLD verdict: within ±10 pp of SPY; "did not lag > 5 pp" reported beside it.
