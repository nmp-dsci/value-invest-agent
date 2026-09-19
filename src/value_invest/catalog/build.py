"""S1a — catalog: every video on the channel with a date, written to ``vi.videos``.

Date precision is recorded per row in ``date_source``:
  supadata   exact, from the Supadata metadata cache (144 videos before the plan ran out)
  yt-dlp     exact, from a per-video yt-dlp extraction (cached; YouTube bot-checks bulk use)
  approx     from the channel tab's "N months ago" text — good enough for window
             years and quarters, not for a T0. `refine_sample_dates` upgrades the
             sampled videos to an exact date."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

import duckdb

from value_invest.catalog.supadata import Supadata
from value_invest.catalog.ytdlp import YtDlpMeta, published_from_ytdlp
from value_invest.config import settings


def _published_supadata(meta: dict[str, Any]) -> date | None:
    raw = meta.get("createdAt") or meta.get("uploadDate")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def year_bucket(d: date, since: date, until: date) -> str | None:
    """Window year: 12 months from `since`, labelled '2022/23'. None outside the window."""
    if d < since or d > until:
        return None
    years = d.year - since.year - (1 if (d.month, d.day) < (since.month, since.day) else 0)
    years = min(
        years, (until.year - since.year) - 1
    )  # the last day of the window closes the last year
    start = since.year + years
    return f"{start}/{str(start + 1)[-2:]}"


def _exact(vid: str, supa: Supadata, ytd: YtDlpMeta) -> tuple[dict[str, Any], date, str] | None:
    """An exact-dated record from either cache, else None. Never hits the network."""
    cached = supa._cache_path("metadata", {"url": f"https://www.youtube.com/watch?v={vid}"})
    if cached.exists():
        try:
            m = json.loads(cached.read_text())["payload"]
            pub = _published_supadata(m)
            if pub:
                media, stats = m.get("media") or {}, m.get("stats") or {}
                return (
                    {
                        "title": m.get("title") or "",
                        "description": m.get("description") or "",
                        "duration": media.get("duration"),
                        "views": stats.get("views"),
                    },
                    pub,
                    "supadata",
                )
        except (KeyError, json.JSONDecodeError):
            pass
    m = ytd.cached(vid)
    if m and (pub := published_from_ytdlp(m)):
        return (
            {
                "title": m.get("title") or "",
                "description": m.get("description") or "",
                "duration": m.get("duration"),
                "views": m.get("view_count"),
            },
            pub,
            "yt-dlp",
        )
    return None


def build_catalog(
    con: duckdb.DuckDBPyConnection, refresh_listing: bool = False, progress: bool = True
) -> dict:
    s = settings()
    supa, ytd = Supadata(), YtDlpMeta()
    listing = ytd.channel_listing(s.channel, refresh=refresh_listing)
    supa_ids = set(supa.channel_video_ids(s.channel_id))  # cached; cross-check only
    now = datetime.now(timezone.utc)
    rows, sources = [], {"supadata": 0, "yt-dlp": 0, "approx": 0, "undated": 0}
    for e in listing:
        vid = e["id"]
        exact = _exact(vid, supa, ytd)
        if exact:
            meta, pub, src = exact
            meta["title"] = meta["title"] or e.get("title") or ""
        else:
            pub = published_from_ytdlp(e)
            src = "approx" if pub else "undated"
            meta = {
                "title": e.get("title") or "",
                "description": e.get("description") or "",
                "duration": e.get("duration"),
                "views": e.get("view_count"),
            }
        sources[src] += 1
        rows.append(
            (
                vid,
                meta["title"],
                meta["description"],
                pub,
                meta["duration"],
                meta["views"],
                year_bucket(pub, s.since, s.until) if pub else None,
                src,
                now,
            )
        )
    con.executemany(
        """INSERT INTO vi.videos (video_id, title, description, published_at, duration_s, view_count, year_bucket, date_source, catalogued_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (video_id) DO UPDATE SET title = excluded.title, description = excluded.description,
             published_at = excluded.published_at, duration_s = excluded.duration_s, view_count = excluded.view_count,
             year_bucket = excluded.year_bucket, date_source = excluded.date_source, catalogued_at = excluded.catalogued_at""",
        rows,
    )
    in_window = sum(1 for r in rows if r[6])
    return {
        "listed_channel_tab": len(listing),
        "listed_supadata": len(supa_ids),
        "only_in_supadata": len(supa_ids - {e["id"] for e in listing}),
        "in_window": in_window,
        "date_sources": sources,
        "ytdlp_calls": ytd.calls,
    }


def refine_dates(
    con: duckdb.DuckDBPyConnection,
    scope: str = "singles",
    limit: int | None = None,
    pace_s: float = 1.2,
) -> dict:
    """Upgrade approximate dates to exact ones with per-video yt-dlp.

    ``scope``: ``sample`` (sampled videos only) or ``singles`` (every video the
    classifier called single whose approximate date lies within a year of the
    window — the channel tab's "N years ago" can be off by up to twelve months,
    so a sample drawn on approximate dates lands outside the window). Paced,
    single-threaded, and stops at the first bot-check so a re-run picks up."""
    import time

    s = settings()
    ytd = YtDlpMeta()
    if scope == "sample":
        where = "in_sample"
    else:
        lo, hi = (
            date(s.since.year - 1, s.since.month, s.since.day),
            date(s.until.year + 1, s.until.month, s.until.day),
        )
        where = f"kind = 'single' AND published_at BETWEEN DATE '{lo}' AND DATE '{hi}'"
    todo = [
        r[0]
        for r in con.execute(
            f"SELECT video_id FROM vi.videos WHERE date_source = 'approx' AND {where} ORDER BY published_at DESC"
        ).fetchall()
    ]
    if limit:
        todo = todo[:limit]
    done, failed, stopped = 0, [], None
    for i, vid in enumerate(todo):
        try:
            m = ytd.video_meta(vid)
        except Exception as e:
            msg = str(e)
            if "not a bot" in msg or "Sign in" in msg:
                stopped = f"bot-check at {i}/{len(todo)}; re-run later"
                break
            failed.append(f"{vid}: {msg[:80]}")
            continue
        pub = published_from_ytdlp(m)
        if not pub:
            failed.append(vid)
            continue
        con.execute(
            "UPDATE vi.videos SET published_at = ?, year_bucket = ?, date_source = 'yt-dlp', duration_s = coalesce(?, duration_s), description = CASE WHEN ? <> '' THEN ? ELSE description END WHERE video_id = ?",
            [
                pub,
                year_bucket(pub, s.since, s.until),
                m.get("duration"),
                m.get("description") or "",
                m.get("description") or "",
                vid,
            ],
        )
        done += 1
        if (i + 1) % 25 == 0:
            print(f"  refined {i + 1}/{len(todo)}", flush=True)
        time.sleep(pace_s)
    return {
        "scope": scope,
        "todo": len(todo),
        "refined": done,
        "failed": failed,
        "stopped": stopped,
        "ytdlp_calls": ytd.calls,
    }
