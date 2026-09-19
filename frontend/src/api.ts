export type Video = {
  video_id: string; title: string; published_at: string | null; duration_s: number | null; view_count: number | null;
  kind: string | null; primary_ticker: string | null; year_bucket: string | null; in_sample: boolean; sample_rank: number | null;
  transcript_status: string; transcript_segments: number | null; confidence: number | null; rationale: string | null;
  tickers: { company: string; yahoo_ticker: string; exchange?: string; is_primary: boolean }[]; company: string | null; currency: string | null;
};
export type Funnel = {
  listed: number; in_window: number; kinds: { kind: string; n: number }[];
  per_year: { year_bucket: string; videos: number; single: number; sampled: number; indexed: number }[];
  sampled: number; indexed: number; since: string; until: string; per_year_target: number; seed: number;
};
export type Segment = { text: string; start_seconds?: number | null; end_seconds?: number | null; offset_ms?: number | null };
export type VideoDetail = {
  video: Video & { description?: string; currency?: string; exchange?: string; benchmark?: string };
  t0: string | null;
  prices: { date: string; close: number; adj_close: number }[];
  benchmark: { date: string; adj_close: number }[];
  price_at_t0?: { date: string; close: number } | null;
  forward?: Record<string, { date: string; close: number } | null>;
  statements: Record<string, { headline: string[]; items: Record<string, Record<string, number>> }>;
  statement_periods: string[];
  statement_period_info?: { period_end: string; n_items: number | null; complete: boolean; from_edgar?: boolean }[];
  statements_hidden_after_t0?: { period_end: string; available_from: string }[];
  transcript: { segments: Segment[]; description?: string; title?: string } | null;
  transcript_error?: string;
  chunks: { chunk_id: string; index: number; start_seconds: number | null; end_seconds: number | null; text: string }[];
  coverage: CoverageRow | null;
  eval?: EvalDetail | null;
};
export type CoverageRow = {
  video_id: string; title: string; t0: string; ticker: string; year_bucket: string; sample_rank: number;
  price_at_t0: number | null; price_date: string | null; fys_visible: number | null; stub_fys_visible?: number | null; latest_fy_visible: string | null;
  fys_total: number | null; earliest_fy: string | null; yahoo_ok: boolean | null; currency: string | null; benchmark: string | null; coverage: string;
};
export type Coverage = { rows: CoverageRow[]; summary: Record<string, number>; tickers: Record<string, unknown>[] };

// ---- M2 · golden evals
export type DataCheck = { reproducible: 'statements' | 'prices' | 'derived' | 'external' | 'judgement'; line_items: string[]; value_stated: number | null; value_as_of: number | null; agrees: boolean | null; formula: string | null; as_of_period: string | null; gap_note: string | null };
export type Reason = { rank: number; direction: 'for_buy' | 'for_sell'; category: string; claim: string; quote: string; chunk_id: string | null; start_s: number | null; feeds: string; metrics: { name: string; value: number | null; unit: string | null; period: string | null }[]; data_check: DataCheck | null };
export type Scenario = { name: 'normal' | 'best' | 'worst'; g_y1_5: number | null; g_y6_10: number | null; terminal_multiple: number | null; probability: number | null; iv_stated: number | null; quote: string };
export type Valuation = { method: string; base_metric: { name: string; value_stated: number | null; quote: string } | null; discount_rate: number | null; payout_ratio: number | null; scenarios: Scenario[]; iv_weighted_stated: number | null; price_mentioned: number | null; what_is_priced_in: { growth: number | null; multiple: number | null; quote: string } | null };
export type Validation = { horizon_m: number; t1: string; ret: number; bench_ret: number; excess: number; verdict: string; verdict_hold_alt: string; iv_hit: boolean | null };
export type EvalRow = {
  video_id: string; ticker: string; t0: string; title: string; year_bucket: string; position: 'BUY' | 'HOLD' | 'SELL'; binary_position: string; hurdle_position: string | null;
  stance_detail: string; personal_action: string; expected_return_pct: number | null; conviction: string; rule_sensitive: boolean; title_says_buy: boolean;
  iv_weighted_stated: number | null; price_at_t0: number | null; split: string; curation_status: string; extractor_version: string;
  checks: Record<string, any>; critic: Record<string, any> | null; headline_quote: string; n_reasons: number; reason_categories: string[];
  validations: Record<string, { excess: number; verdict: string; verdict_hold_alt: string; iv_hit: boolean | null; t1: string }>;
};
export type EvalDetail = EvalRow & { valuation: Valuation; iv_recomputed: Record<string, any>; reasons: Reason[]; external_facts: string[]; validations: Validation[]; review_note: string | null; reviewed_at: string | null; model: string; transcript_sha256: string };
export type Bucket = { n: number; mix: Record<string, number>; hits: Record<string, [number, number]>; mean_excess: Record<string, number | null>; verdict: Record<string, number>; verdict_hold_alt: Record<string, number>; iv_hit: [number, number] };
export type EvalSummary = {
  validation: { by_year: Record<string, Record<string, Bucket>>; overall: Record<string, Bucket>; splits: Record<string, number>; n_evals: number };
  mix: { year_bucket: string; split: string; n: number; buy: number; hold: number; sell: number; reviewed: number; rule_sensitive: number }[];
  cuts: { rule: string; label: string; n: number }[];
  stats: Record<string, number | null>;
  reproducible: { reproducible: string; n: number }[];
  seed_eval_v0?: Record<string, any>; kappa?: Record<string, any>; method_summary?: Record<string, any>;
};

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json() as Promise<T>;
}
export const api = {
  health: () => get<{ ok: boolean; mode: string; tables: Record<string, number> }>('/api/health'),
  funnel: () => get<Funnel>('/api/funnel'),
  videos: (sample: boolean) => get<Video[]>(`/api/videos?sample=${sample}`),
  video: (id: string) => get<VideoDetail>(`/api/videos/${id}`),
  coverage: () => get<Coverage>('/api/market/coverage'),
  evals: () => get<EvalRow[]>('/api/evals'),
  evalSummary: () => get<EvalSummary>('/api/evals/summary'),
  eval: (id: string) => get<EvalDetail>(`/api/evals/${id}`),
  review: async (id: string, body: { curation_status: string; note?: string; stance_detail?: string }) => {
    const r = await fetch(`/api/evals/${id}/review`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`${r.status} review`);
    return r.json() as Promise<{ video_id: string; curation_status: string; stance_detail: string; position: string }>;
  },
};
