"""S1d — ingest through transcript·lab, never around it.

Each sampled video is indexed by running transcript·lab's own CLI in its own
checkout (``uv run python -m src.cli index-rag <url>``), so the transcript,
chunks and embeddings land in *its* Chroma store exactly as if the workbench
had ingested them. We then read the raw document back (``ingest.corpus``) to
record the segment count and status on ``vi.videos``."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import duckdb

from value_invest.config import settings
from value_invest.ingest.corpus import Corpus


def supadata_shaped_metadata(video_id: str) -> dict | None:
    """The video's cached metadata in Supadata ``/metadata`` shape, or None.

    transcript·lab's fetcher bills two Supadata credits per video — transcript
    plus metadata — unless the caller supplies the metadata. We already hold it
    from the catalog (Supadata cache or yt-dlp), so ``vi ingest`` always passes
    it and pays one credit. Fetching metadata is transcript·lab's default; this
    is the explicit override."""
    from value_invest.catalog.supadata import Supadata
    from value_invest.catalog.ytdlp import YtDlpMeta

    supa_cache = Supadata()._cache_path(
        "metadata", {"url": f"https://www.youtube.com/watch?v={video_id}"}
    )
    if supa_cache.exists():
        try:
            return json.loads(supa_cache.read_text())["payload"]
        except (KeyError, json.JSONDecodeError):
            pass
    m = YtDlpMeta().cached(video_id)
    if not m:
        return None
    created = None
    if m.get("timestamp"):
        created = datetime.fromtimestamp(int(m["timestamp"]), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
    elif m.get("upload_date"):
        u = str(m["upload_date"])
        created = f"{u[:4]}-{u[4:6]}-{u[6:8]}T00:00:00.000Z"
    return {
        "platform": "youtube",
        "type": "video",
        "id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": m.get("title"),
        "description": m.get("description"),
        "author": {
            "displayName": settings().extra.get(
                "channel_name", "Value Investing with Sven Carlin, Ph.D."
            )
        },
        "stats": {"views": m.get("view_count")},
        "media": {"type": "video", "duration": m.get("duration")},
        "createdAt": created,
        "additionalData": {"channelId": m.get("channel_id") or settings().channel_id},
    }


def _index_one(video_id: str, refresh: bool) -> tuple[str, int, str]:
    s = settings()
    url = f"https://www.youtube.com/watch?v={video_id}"
    argv = ["uv", "run", "python", "-m", "src.cli", "index-rag", url]
    if refresh:
        argv.append("--refresh")
    meta = supadata_shaped_metadata(video_id)
    if meta is not None:
        path = s.cache_dir / "ingest_meta" / f"{video_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta))
        argv += ["--metadata-json", str(path)]
    proc = subprocess.run(
        argv, cwd=s.transcript_lab_root, capture_output=True, text=True, timeout=900
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    return video_id, proc.returncode, " | ".join(tail)[:400]


def ingest_sample(
    con: duckdb.DuckDBPyConnection, concurrency: int = 2, refresh: bool = False
) -> dict:
    corpus = Corpus()
    todo = [
        r[0]
        for r in con.execute(
            "SELECT video_id FROM vi.videos WHERE in_sample ORDER BY published_at"
        ).fetchall()
    ]
    already = [] if refresh else [v for v in todo if corpus.has(v)]
    pending = [v for v in todo if v not in already]
    results: list[tuple[str, int, str]] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for vid, code, tail in pool.map(lambda v: _index_one(v, refresh), pending):
            results.append((vid, code, tail))
            print(f"  {vid}  rc={code}  {tail[:120]}", flush=True)
    failed = []
    for vid in todo:
        doc = corpus.raw(vid)
        if doc is not None and not corpus.chunks(vid):  # transcript stored but chunking failed
            doc = None
        if doc is None:
            failed.append(vid)
            con.execute(
                "UPDATE vi.videos SET transcript_status = 'failed' WHERE video_id = ?", [vid]
            )
        else:
            con.execute(
                "UPDATE vi.videos SET transcript_status = 'indexed', transcript_segments = ? WHERE video_id = ?",
                [len(doc["segments"]), vid],
            )
    return {
        "sampled": len(todo),
        "already_indexed": len(already),
        "ran_index_rag": len(pending),
        "indexed": len(todo) - len(failed),
        "failed": failed,
        "errors": [(v, t) for v, c, t in results if c != 0],
    }
