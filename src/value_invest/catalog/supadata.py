"""A thin Supadata client with the same disk-cache idea as transcript·lab's
``src/transcripts/discovery.py``: every GET is cached by (path, params) under
``.vi/supadata/`` so re-running the catalog costs nothing."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from value_invest.config import settings

BASE = "https://api.supadata.ai/v1"
# Supadata 429s at a few requests/second; one global pacer keeps every worker
# under that regardless of the pool size.
PACE_SECONDS = 0.35
_pace_lock = threading.Lock()


class SupadataError(RuntimeError):
    pass


class Supadata:
    def __init__(self, api_key: str | None = None, cache_dir: Path | None = None) -> None:
        self.api_key = api_key or settings().supadata_api_key
        if not self.api_key:
            raise SupadataError("SUPADATA_API_KEY is not set (./.env or ~/.env)")
        self.cache_dir = cache_dir or settings().cache_dir / "supadata"
        self.calls = 0  # network calls this process, for the spend report
        self.rate_limited = 0

    def channel_video_ids(self, channel: str, limit: int = 5000) -> list[str]:
        data = self._get("youtube/channel/videos", {"id": channel, "limit": limit, "type": "video"})
        return [str(v) for v in data.get("videoIds", [])]

    def channel(self, channel: str) -> dict[str, Any]:
        return self._get("youtube/channel", {"id": channel})

    def metadata(self, video_id: str) -> dict[str, Any]:
        return self._get("metadata", {"url": f"https://www.youtube.com/watch?v={video_id}"})

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        cache = self._cache_path(path, params)
        if cache.exists():
            try:
                return json.loads(cache.read_text())["payload"]
            except (OSError, KeyError, json.JSONDecodeError):
                pass
        last: Exception | None = None
        for attempt in range(12):
            try:
                with _pace_lock:
                    time.sleep(PACE_SECONDS)
                r = httpx.get(
                    f"{BASE}/{path}", params=params, headers={"x-api-key": self.api_key}, timeout=60
                )
                self.calls += 1
                if r.status_code == 429:
                    # Honour Retry-After when given, else back off geometrically (2s → 64s).
                    wait = float(r.headers.get("retry-after") or min(2 ** (attempt + 1), 64))
                    self.rate_limited += 1
                    time.sleep(wait)
                    continue
                if r.status_code >= 400:
                    raise SupadataError(f"HTTP {r.status_code} for {path}: {r.text[:200]}")
                payload = r.json()
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(
                    json.dumps(
                        {"cached_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
                    )
                )
                return payload
            except httpx.HTTPError as e:
                last = e
                time.sleep(1.0 * (attempt + 1))
        raise SupadataError(f"request failed for {path}: {last or 'rate limited'}")

    def _cache_path(self, path: str, params: dict[str, Any]) -> Path:
        digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:24]
        return self.cache_dir / path.replace("/", "_") / f"{digest}.json"
