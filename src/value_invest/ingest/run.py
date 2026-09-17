"""S1d — ingest through transcript·lab, never around it.

Each sampled video is indexed by running transcript·lab's own CLI in its own
checkout (``uv run python -m src.cli index-rag <url>``), so the transcript,
chunks and embeddings land in *its* Chroma store exactly as if the workbench
had ingested them. We then read the raw document back (``ingest.corpus``) to
record the segment count and status on ``vi.videos``."""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor

import duckdb

from value_invest.config import settings
from value_invest.ingest.corpus import Corpus


def _index_one(video_id: str, refresh: bool) -> tuple[str, int, str]:
    s = settings()
    url = f"https://www.youtube.com/watch?v={video_id}"
    argv = ["uv", "run", "python", "-m", "src.cli", "index-rag", url]
    if refresh:
        argv.append("--refresh")
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
