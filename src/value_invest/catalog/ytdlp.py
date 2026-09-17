"""Credit-free video metadata via yt-dlp.

Two routes, in order of date precision:

* ``video_meta`` — one watch-page extraction per video: exact upload date,
  duration, views, description. YouTube bot-checks this after a few hundred
  calls from one IP ("Sign in to confirm you're not a bot"), so it is used
  for the sampled videos, not the whole channel.
* ``channel_listing`` — the channel's Videos tab in one flat call with yt-dlp's
  ``youtubetab:approximate_date`` extractor arg, which turns each entry's
  "N months ago" text into a timestamp. Day-accurate for recent uploads,
  month/year-accurate for old ones — enough to place a video in a window year
  and sample by quarter, not enough to be a T0.

Supadata's ``/metadata`` (exact, one plan credit each) is the third source and
is only read from its cache here — the plan ran out at video 144.
Every result is cached under ``.vi/ytdlp/``."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from value_invest.config import settings


class YtDlpMeta:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or settings().cache_dir / "ytdlp"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.calls = 0

    def cached(self, video_id: str) -> dict[str, Any] | None:
        cache = self.cache_dir / f"{video_id}.json"
        if cache.exists():
            try:
                return json.loads(cache.read_text())
            except json.JSONDecodeError:
                return None
        return None

    def video_meta(self, video_id: str) -> dict[str, Any]:
        hit = self.cached(video_id)
        if hit:
            return hit
        import yt_dlp

        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noprogress": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        self.calls += 1
        slim = {
            "id": info.get("id"),
            "title": info.get("title"),
            "description": (info.get("description") or "")[:2000],
            "upload_date": info.get("upload_date"),
            "timestamp": info.get("timestamp"),
            "duration": info.get("duration"),
            "view_count": info.get("view_count"),
            "channel_id": info.get("channel_id"),
            "has_auto_captions": bool(info.get("automatic_captions")),
        }
        (self.cache_dir / f"{video_id}.json").write_text(json.dumps(slim))
        return slim

    def channel_listing(self, handle: str, refresh: bool = False) -> list[dict[str, Any]]:
        """Every entry on the Videos tab: id, title, duration, views, approximate timestamp."""
        cache = self.cache_dir / f"_listing_{handle.strip('@')}.json"
        if cache.exists() and not refresh:
            return json.loads(cache.read_text())["entries"]
        import yt_dlp

        opts = {
            "quiet": True, "no_warnings": True, "skip_download": True, "noprogress": True,
            "extract_flat": True,
            "extractor_args": {"youtubetab": {"approximate_date": ["1"]}},
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/{handle}/videos", download=False)
        self.calls += 1
        entries = [
            {
                "id": e.get("id"),
                "title": e.get("title"),
                "description": e.get("description") or "",
                "timestamp": e.get("timestamp"),
                "duration": e.get("duration"),
                "view_count": e.get("view_count"),
            }
            for e in (info.get("entries") or [])
            if e and e.get("id")
        ]
        cache.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "entries": entries}))
        return entries


def published_from_ytdlp(meta: dict[str, Any]) -> date | None:
    if meta.get("timestamp"):
        return datetime.fromtimestamp(int(meta["timestamp"]), tz=timezone.utc).date()
    if meta.get("upload_date"):
        return datetime.strptime(str(meta["upload_date"]), "%Y%m%d").date()
    return None
