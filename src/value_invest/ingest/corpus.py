"""Read-only view of transcript·lab's Chroma corpus.

Ids and document shapes are transcript·lab's own (``src/rag/storage.py``):
``raw_transcript:<video_id>`` holds a JSON body with ``segments`` and the
video metadata; ``chunk:<video_id>:<i>`` are the retrieval chunks. Nothing
here writes."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from value_invest.config import settings


class Corpus:
    def __init__(self) -> None:
        import chromadb

        self.client = chromadb.PersistentClient(path=str(settings().transcript_lab_chroma))
        self.raw_col = self.client.get_or_create_collection("raw_transcripts")
        self.chunk_col = self.client.get_or_create_collection("transcript_chunks")

    def has(self, video_id: str) -> bool:
        return bool(self.raw_col.get(ids=[f"raw_transcript:{video_id}"]).get("ids"))

    def raw(self, video_id: str) -> dict[str, Any] | None:
        res = self.raw_col.get(
            ids=[f"raw_transcript:{video_id}"], include=["documents", "metadatas"]
        )
        if not res.get("ids"):
            return None
        body = json.loads((res.get("documents") or ["{}"])[0])
        meta = (res.get("metadatas") or [{}])[0] or {}
        return {
            "video_id": video_id,
            "title": meta.get("title"),
            "channel_id": meta.get("channel_id"),
            "channel_name": meta.get("channel_name"),
            "upload_date": meta.get("upload_date"),
            "duration_seconds": meta.get("duration_seconds"),
            "description": body.get("description") or meta.get("description"),
            "segments": body.get("segments", []),
        }

    def chunks(self, video_id: str) -> list[dict[str, Any]]:
        res = self.chunk_col.get(where={"video_id": video_id}, include=["documents", "metadatas"])
        out = []
        for cid, doc, meta in zip(
            res.get("ids", []), res.get("documents") or [], res.get("metadatas") or []
        ):
            m = meta or {}
            out.append(
                {
                    "chunk_id": cid,
                    "index": m.get("chunk_index"),
                    "start_seconds": m.get("start_seconds"),
                    "end_seconds": m.get("end_seconds"),
                    "text": doc,
                }
            )
        out.sort(key=lambda c: (c["index"] is None, c["index"]))
        return out

    def channel_video_ids(self, channel_id: str) -> list[str]:
        res = self.raw_col.get(where={"channel_id": channel_id}, include=["metadatas"])
        return [str((m or {}).get("video_id")) for m in res.get("metadatas") or []]


@lru_cache(maxsize=1)
def corpus() -> Corpus:
    return Corpus()
