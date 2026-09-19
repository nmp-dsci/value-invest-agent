"""Stage 2 — one Agent SDK call turns a transcript into a ``GoldenEvalDraft``.

The prompt carries the description head and the chunk-marked transcript; the
system prompt is the extractor version's ``system.md``. The model has no
tools and never sees the title, prices, or statements — the title is
title-blind by design (see checkpoint.title_says_buy) and never reaches
the extractor as evidence."""

from __future__ import annotations

from typing import Any

from value_invest.golden.models import GoldenEvalDraft
from value_invest.golden.transcript import Transcript
from value_invest.golden.versions import ExtractorVersion
from value_invest.llm import run_structured_sync


def build_prompt(t: Transcript, ticker: str, t0: str, description: str | None) -> str:
    desc = (description or "").strip().replace("\n", " ")[:400]
    return (
        f"video_id: {t.video_id}\nticker: {ticker}\nvideo date (T0): {t0}\n"
        f"description (head): {desc}\n\n"
        f"TRANSCRIPT ({t.words} words, {t.n_chunks} chunks; each chunk starts with its marker):\n\n"
        f"{t.marked}\n\n"
        "Extract the golden eval as ONE JSON object per the system instructions."
    )


def run_extract(
    t: Transcript, ticker: str, t0: str, description: str | None, version: ExtractorVersion
) -> tuple[GoldenEvalDraft, dict[str, Any]]:
    draft, usage = run_structured_sync(
        build_prompt(t, ticker, t0, description),
        schema=GoldenEvalDraft,
        system_prompt=version.system_prompt,
        model=version.model,
        max_turns=version.max_turns,
        effort=version.effort,
    )
    # the model occasionally echoes a different id/ticker; the caller's are authoritative
    draft.video_id, draft.ticker = t.video_id, ticker
    for i, r in enumerate(sorted(draft.reasons, key=lambda r: r.rank), 1):
        r.rank = i
    draft.reasons = sorted(draft.reasons, key=lambda r: r.rank)[:5]
    return draft, usage
