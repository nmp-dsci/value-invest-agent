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
  statements_hidden_after_t0?: { period_end: string; available_from: string }[];
  transcript: { segments: Segment[]; description?: string; title?: string } | null;
  transcript_error?: string;
  chunks: { chunk_id: string; index: number; start_seconds: number | null; end_seconds: number | null; text: string }[];
  coverage: CoverageRow | null;
};
export type CoverageRow = {
  video_id: string; title: string; t0: string; ticker: string; year_bucket: string; sample_rank: number;
  price_at_t0: number | null; price_date: string | null; fys_visible: number | null; latest_fy_visible: string | null;
  fys_total: number | null; earliest_fy: string | null; yahoo_ok: boolean | null; currency: string | null; benchmark: string | null; coverage: string;
};
export type Coverage = { rows: CoverageRow[]; summary: Record<string, number>; tickers: Record<string, unknown>[] };

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
};
