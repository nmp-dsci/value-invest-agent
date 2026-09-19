"""Train / test / holdout for the golden evals (spec D15).

*train* and *test* are stamped on the eval, not on the year: inside every window
year the sampled videos are ranked by a seeded hash of ``video_id`` and the top
``test_share`` become test. The agent (M3) is tuned on train and gated on test
across the same years, so it is checked on history it never saw rather than only
on the newest year. *holdout* is not a label — it is the state of an eval at a
horizon whose outcome is not yet in the price table (``T0 + h`` after the last
close). It therefore shrinks as the horizon shortens: at +6 m nearly everything
has an answer, at +24 m the last two window years are still open.
``vi.split_at(h)`` gives the per-horizon view in SQL."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb

from value_invest.config import ROOT, settings

EVALS_DIR = ROOT / "data" / "golden" / "evals"


def rank_key(video_id: str, seed: str) -> str:
    return hashlib.sha1(f"{seed}:{video_id}".encode()).hexdigest()


def assign(videos_by_year: dict[str, list[str]], test_share: float, seed: str) -> dict[str, str]:
    """Deterministic within-year split: ``round(n × share)`` test per year (never
    the whole year), the rest train. Independent of labels, so a review that
    changes a position never moves a video between splits."""
    out: dict[str, str] = {}
    for _yb, ids in videos_by_year.items():
        ranked = sorted(set(ids), key=lambda v: rank_key(v, seed))
        n_test = min(len(ranked) - 1, int(len(ranked) * test_share + 0.5)) if len(ranked) > 1 else 0
        for i, vid in enumerate(ranked):
            out[vid] = "test" if i < n_test else "train"
    return out


def assign_splits(
    con: duckdb.DuckDBPyConnection, patch_cache: bool = True, evals_dir: Path = EVALS_DIR
) -> dict[str, Any]:
    """Stamp ``vi.evals.split`` for every eval and mirror it into the cached
    ``data/golden/evals/<video_id>.json`` so the checkpoint and the table agree."""
    s = settings()
    rows = con.execute(
        "SELECT e.video_id, coalesce(v.year_bucket, '?') FROM vi.evals e LEFT JOIN vi.videos v USING (video_id)"
    ).fetchall()
    by_year: dict[str, list[str]] = defaultdict(list)
    for vid, yb in rows:
        by_year[yb].append(vid)
    labels = assign(by_year, s.test_share, s.split_seed)
    changed = 0
    for vid, split in labels.items():
        cur = con.execute("SELECT split FROM vi.evals WHERE video_id = ?", [vid]).fetchone()
        if cur and cur[0] != split:
            con.execute("UPDATE vi.evals SET split = ? WHERE video_id = ?", [split, vid])
            changed += 1
        if patch_cache:
            p = evals_dir / f"{vid}.json"
            if p.exists():
                d = json.loads(p.read_text())
                if d.get("eval", {}).get("split") != split:
                    d["eval"]["split"] = split
                    p.write_text(json.dumps(d, indent=1, default=str))
    per_year = {
        yb: {
            "train": sum(labels[v] == "train" for v in ids),
            "test": sum(labels[v] == "test" for v in ids),
        }
        for yb, ids in sorted(by_year.items())
    }
    return {
        "test_share": s.test_share,
        "seed": s.split_seed,
        "changed": changed,
        "per_year": per_year,
        "train": sum(v == "train" for v in labels.values()),
        "test": sum(v == "test" for v in labels.values()),
    }
