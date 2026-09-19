"""S1b — title classifier. Batches of titles → one Agent SDK call → labels.

`kind`:
  single  — one company is the subject (a ticker regex would miss most of
            these: "LVMH Stock…", "Nike Stock…")
  multi   — several named stocks compared, or a list ("10 Stocks to Buy")
  macro   — markets, rates, crashes, portfolio strategy
  other   — channel/platform/meta, ETFs, criticism, Q&A

The 40 hand-labelled titles under data/samples are the eval (`--eval-seed`)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import duckdb

from value_invest.classify.models import TitleLabel, TitleLabelBatch
from value_invest.config import ROOT
from value_invest.llm import run_structured_sync

CLASSIFIER_VERSION = "title-v1"

SYSTEM = """You label YouTube video titles from a value-investing channel (Sven Carlin).
For each item return exactly one label object. Rules:
- kind=single: ONE company is the subject of the video (even if the title only names the company,
  e.g. "Nike Stock…", "LVMH Stock Analysis…", "BRK a Buy or Sell?"). Give its Yahoo Finance ticker
  with exchange suffix where not US-listed (MC.PA, VNA.DE, 0700.HK, 7974.T, CSU.TO, AD.AS, VTY.L).
  Prefer the primary listing over an ADR unless the title uses the US ticker. Berkshire → BRK-B.
- kind=multi: several named stocks compared, or a numbered list of stocks ("10 Stocks to Buy",
  "3 Great Buys", "Ackman's stocks"). List the tickers you can identify from the title; may be empty.
- kind=macro: markets, rates, crashes, debt, valuations in general, no specific company as subject.
- kind=other: channel/platform/meta, ETF/index strategy, investing philosophy, Q&A, criticism.
- confidence in [0,1]; rationale ≤ 15 words.
Return ONLY a JSON object: {"labels": [ {video_id, kind, tickers:[{company, yahoo_ticker, exchange, is_primary}], confidence, rationale}, ... ]}
with one entry per input video_id, in input order."""


def _prompt(items: list[dict[str, Any]]) -> str:
    lines = []
    for it in items:
        desc = (it.get("description") or "").strip().replace("\n", " ")[:160]
        lines.append(
            json.dumps(
                {
                    "video_id": it["video_id"],
                    "title": it["title"],
                    "published": str(it.get("published_at") or ""),
                    "description_head": desc,
                }
            )
        )
    return "Label these videos:\n" + "\n".join(lines)


def classify_items(
    items: list[dict[str, Any]], model: str | None = None
) -> tuple[list[TitleLabel], dict]:
    batch, usage = run_structured_sync(
        _prompt(items), schema=TitleLabelBatch, system_prompt=SYSTEM, model=model, max_turns=2
    )
    wanted = {it["video_id"] for it in items}
    labels = [lab for lab in batch.labels if lab.video_id in wanted]
    return labels, usage


def _upsert(con: duckdb.DuckDBPyConnection, labels: list[TitleLabel], source: str) -> None:
    now = datetime.now(timezone.utc)
    con.executemany(
        """INSERT INTO vi.title_labels (video_id, kind, tickers, confidence, rationale, source,
                                        classifier_version, labelled_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (video_id) DO UPDATE SET kind = excluded.kind, tickers = excluded.tickers,
             confidence = excluded.confidence, rationale = excluded.rationale,
             source = excluded.source, classifier_version = excluded.classifier_version,
             labelled_at = excluded.labelled_at""",
        [
            (
                lab.video_id,
                lab.kind,
                json.dumps([t.model_dump() for t in lab.tickers]),
                lab.confidence,
                lab.rationale,
                source,
                CLASSIFIER_VERSION,
                now,
            )
            for lab in labels
        ],
    )
    # mirror kind + primary ticker onto vi.videos for cheap filtering
    con.execute(
        """UPDATE vi.videos v SET kind = l.kind,
             primary_ticker = (SELECT t->>'yahoo_ticker' FROM (SELECT unnest(from_json(l.tickers, '["JSON"]')) AS t) WHERE (t->>'is_primary') = 'true' LIMIT 1)
           FROM vi.title_labels l WHERE l.video_id = v.video_id"""
    )


def classify_catalog(
    con: duckdb.DuckDBPyConnection,
    batch: int = 40,
    limit: int | None = None,
    only_missing: bool = True,
    workers: int = 3,
) -> dict:
    where = "WHERE v.year_bucket IS NOT NULL"
    if only_missing:
        where += " AND l.video_id IS NULL"
    q = f"""SELECT v.video_id, v.title, v.description, v.published_at FROM vi.videos v
            LEFT JOIN vi.title_labels l ON l.video_id = v.video_id {where}
            ORDER BY v.published_at DESC"""
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = [
        dict(zip(["video_id", "title", "description", "published_at"], r))
        for r in con.execute(q).fetchall()
    ]
    done, calls, tokens = 0, 0, 0
    batches = [rows[i : i + batch] for i in range(0, len(rows), batch)]
    from concurrent.futures import ThreadPoolExecutor

    def one(items):
        try:
            return classify_items(items), None
        except Exception as e:  # a failed batch is reported and skipped; re-run picks it up
            return ([], {}), f"{type(e).__name__}: {str(e)[:120]}"

    errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for (labels, usage), err in pool.map(one, batches):
            if err:
                errors.append(err)
            _upsert(con, labels, source="llm")
            done += len(labels)
            calls += 1
            tokens += int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
            print(
                f"  labelled {done}/{len(rows)}  sdk_calls={calls}  errors={len(errors)}",
                flush=True,
            )
    kinds = dict(
        con.execute(
            "SELECT kind, count(*) FROM vi.videos WHERE year_bucket IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    )
    return {
        "labelled": done,
        "sdk_calls": calls,
        "tokens": tokens,
        "errors": errors,
        "kinds_in_window": kinds,
    }


def evaluate_seed(model: str | None = None) -> dict:
    """Classifier vs the 40 hand labels: agreement on kind, and on primary ticker for singles."""
    seed = json.loads((ROOT / "data/samples/titles_2026-09_labels.json").read_text())
    meta = {m["id"]: m for m in json.loads((ROOT / "data/samples/titles_2026-09.json").read_text())}
    items = [
        {"video_id": s["id"], "title": s["title"], "description": meta[s["id"]].get("desc", "")}
        for s in seed
    ]
    labels, usage = classify_items(items, model=model)
    by_id = {lab.video_id: lab for lab in labels}
    kind_ok = 0
    ticker_ok = ticker_n = 0
    disagreements = []
    for s in seed:
        lab = by_id.get(s["id"])
        if lab is None:
            disagreements.append({"title": s["title"], "human": s["kind"], "llm": None})
            continue
        if lab.kind == s["kind"]:
            kind_ok += 1
        else:
            disagreements.append({"title": s["title"], "human": s["kind"], "llm": lab.kind})
        if s["kind"] == "single":
            ticker_n += 1
            primary = next((t.yahoo_ticker for t in lab.tickers if t.is_primary), None)
            if primary and primary.upper() == s["tickers"][0].upper():
                ticker_ok += 1
            else:
                disagreements.append(
                    {"title": s["title"], "human_ticker": s["tickers"][0], "llm_ticker": primary}
                )
    result = {
        "n": len(seed),
        "kind_agreement": round(kind_ok / len(seed), 3),
        "ticker_agreement_on_singles": round(ticker_ok / max(ticker_n, 1), 3),
        "disagreements": disagreements,
        "usage": usage,
    }
    (ROOT / "data/samples/classifier_seed_eval.json").write_text(
        json.dumps(result, indent=1, default=str)
    )
    return result
