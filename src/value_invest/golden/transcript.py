"""Transcript text with chunk anchors, and its hash.

transcript·lab stores the raw segments and the retrieval chunks; a chunk carries
``chunk_index`` and ``start_seconds``. The extractor is shown the chunk text
with a marker in front of each chunk (``[chunk:<video_id>:<i> @ m:ss]``) so a
reason can cite the chunk and the second it sits in. The hash is over the
segment text, so a re-ingest that changes nothing costs nothing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from value_invest.ingest.corpus import Corpus, corpus


def mmss(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


@dataclass(frozen=True)
class Transcript:
    video_id: str
    title: str
    text: str  # plain, segments joined
    marked: str  # chunks with [chunk:id:i @ m:ss] markers
    sha256: str
    n_segments: int
    n_chunks: int
    words: int
    chunk_starts: dict[str, float | None]


def load_transcript(video_id: str, c: Corpus | None = None) -> Transcript | None:
    c = c or corpus()
    raw = c.raw(video_id)
    if raw is None:
        return None
    segs = raw["segments"]
    text = " ".join((s.get("text") or "").strip() for s in segs if (s.get("text") or "").strip())
    chunks = c.chunks(video_id)
    parts, starts = [], {}
    for ch in chunks:
        cid = ch["chunk_id"]
        starts[cid] = ch.get("start_seconds")
        parts.append(f"[{cid} @ {mmss(ch.get('start_seconds'))}] {ch['text'].strip()}")
    marked = "\n\n".join(parts) if parts else text
    return Transcript(
        video_id=video_id,
        title=raw.get("title") or "",
        text=text,
        marked=marked,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        n_segments=len(segs),
        n_chunks=len(chunks),
        words=len(text.split()),
        chunk_starts=starts,
    )


def find_quote(quote: str, text: str, min_ratio: float = 0.9) -> float:
    """How well ``quote`` is found verbatim in ``text``: 1.0 exact, else the best
    windowed similarity (ASR text drops punctuation and mangles names, so a
    fuzzy match ≥ 0.9 counts as verbatim)."""
    import difflib

    q = " ".join(quote.lower().split())
    t = " ".join(text.lower().split())
    if not q:
        return 0.0
    if q in t:
        return 1.0
    words_q = q.split()
    words_t = t.split()
    n = len(words_q)
    if n == 0 or len(words_t) < n:
        return difflib.SequenceMatcher(None, q, t).ratio()
    best = 0.0
    step = max(1, n // 3)
    for i in range(0, len(words_t) - n + 1, step):
        window = " ".join(words_t[i : i + n + 2])
        r = difflib.SequenceMatcher(None, q, window).ratio()
        if r > best:
            best = r
            if best >= 0.98:
                break
    return best
