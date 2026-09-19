"""S1c — the seeded, stratified sample.

10 single-stock videos per window year (4 years → 40). Within a year the draw
is stratified by quarter so the picks spread over time instead of clumping,
and the order is fixed by the seed so raising ``--per-year`` only *adds*
videos: every earlier pick keeps its ``sample_rank``. Videos are eligible when
the classifier says ``single`` with a primary ticker and confidence ≥ 0.6 **and
the date is exact** (`refine-dates` first): the channel tab's approximate
dates are off by up to a year, which put a third of a first draw outside the
window."""

from __future__ import annotations

import random
from collections import defaultdict

import duckdb

from value_invest.config import settings

MIN_CONFIDENCE = 0.6


def draw_sample(
    con: duckdb.DuckDBPyConnection,
    per_year: int | None = None,
    seed: int | None = None,
    edgar_only: bool | None = None,
) -> dict:
    s = settings()
    per_year = per_year or s.sample_per_year
    seed = s.sample_seed if seed is None else seed
    edgar_only = s.sample_edgar_only if edgar_only is None else edgar_only
    rows = con.execute(
        f"""SELECT v.video_id, v.year_bucket, v.published_at, v.primary_ticker
           FROM vi.videos v JOIN vi.title_labels l USING (video_id)
           LEFT JOIN vi.tickers t ON t.ticker = v.primary_ticker
           WHERE v.year_bucket IS NOT NULL AND l.kind = 'single'
             AND v.date_source IN ('supadata', 'yt-dlp')   -- exact dates only: approx is ±12 months
             AND v.primary_ticker IS NOT NULL AND coalesce(l.confidence, 0) >= ?
             {"AND t.edgar_filer" if edgar_only else ""}   -- US stocks with 10-K filings (vi edgar --check-candidates)
           ORDER BY v.published_at""",
        [MIN_CONFIDENCE],
    ).fetchall()
    by_year: dict[str, list[tuple]] = defaultdict(list)
    for r in rows:
        by_year[r[1]].append(r)
    # Sticky: a video already in the sample that is still eligible keeps its slot
    # and rank, so a change of eligibility (e.g. EDGAR-only) or of seed only
    # replaces what has to be replaced — every kept video's transcript and
    # market data stay useful.
    eligible_ids = {r[0] for r in rows}
    prior: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for vid, year, rank in con.execute(
        "SELECT video_id, year_bucket, sample_rank FROM vi.videos WHERE in_sample AND sample_rank IS NOT NULL ORDER BY sample_rank"
    ).fetchall():
        if vid in eligible_ids:
            prior[year].append((vid, rank))
    picks: list[tuple[str, int]] = []
    per_bucket: dict[str, int] = {}
    kept_total = 0
    for year in sorted(by_year):
        seen_tickers: set[str] = set()  # distinct-ticker preference is per year, so a
        # bigger draw in one year never reorders another year's picks
        rng = random.Random(f"{seed}:{year}")
        # round-robin over quarters, each quarter's candidates shuffled by the seed
        quarters: dict[int, list[tuple]] = defaultdict(list)
        for r in by_year[year]:
            quarters[(r[2].month - 1) // 3].append(r)
        for q in quarters.values():
            rng.shuffle(q)
        order: list[tuple] = []
        while any(quarters.values()) and len(order) < len(by_year[year]):
            for q in sorted(quarters):
                if quarters[q]:
                    order.append(quarters[q].pop())
        by_id = {r[0]: r for r in by_year[year]}
        kept = [by_id[vid] for vid, _ in prior.get(year, []) if vid in by_id][:per_year]
        kept_ids = {r[0] for r in kept}
        seen_tickers.update(r[3] for r in kept)
        kept_total += len(kept)
        chosen: list[tuple] = list(kept)
        deferred: list[tuple] = []
        for r in order:  # prefer distinct tickers within a year; fall back to repeats
            if r[0] in kept_ids:
                continue
            if len(chosen) >= per_year:
                break
            (chosen if r[3] not in seen_tickers else deferred).append(r)
            if r[3] not in seen_tickers:
                seen_tickers.add(r[3])
        chosen = (chosen + deferred)[:per_year]
        per_bucket[year] = len(chosen)
        for i, r in enumerate(chosen, 1):
            picks.append((r[0], i))
    con.execute("UPDATE vi.videos SET in_sample = FALSE, sample_rank = NULL")
    con.executemany(
        "UPDATE vi.videos SET in_sample = TRUE, sample_rank = ? WHERE video_id = ?",
        [(rank, vid) for vid, rank in picks],
    )
    approx_singles = con.execute(
        "SELECT count(*) FROM vi.videos WHERE kind = 'single' AND date_source = 'approx' AND year_bucket IS NOT NULL"
    ).fetchone()[0]
    return {
        "edgar_only": edgar_only,
        "kept_from_previous_sample": kept_total,
        "approx_dated_singles_excluded": approx_singles,
        "per_year": per_year,
        "seed": seed,
        "eligible_single": len(rows),
        "sampled": len(picks),
        "per_bucket": per_bucket,
        "distinct_tickers": len({r[3] for r in rows if any(p[0] == r[0] for p in picks)}),
    }
