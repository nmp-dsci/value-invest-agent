"""Stage 5 — cache, ``vi.evals``, the seed eval, κ and the method summary.

A finished eval is cached at ``data/golden/evals/<video_id>.json`` under the key
(video_id, transcript sha, extractor version + prompt fingerprint): re-running
``vi extract`` costs nothing unless the transcript or the prompt changed."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Any

import duckdb

from value_invest.config import ROOT, settings
from value_invest.golden.critic import run_critic
from value_invest.golden.extract import run_extract
from value_invest.golden.ground import ground
from value_invest.golden.kappa import kappa_report
from value_invest.golden.models import (
    THREE_WAY,
    Critic,
    GoldenEval,
    GoldenEvalDraft,
    Provenance,
    binary_for,
    hurdle_for,
    position_for,
    title_says_buy,
)
from value_invest.golden.transcript import Transcript, load_transcript
from value_invest.golden.versions import ExtractorVersion, load_version
from value_invest.llm import resolve_model

GOLDEN_DIR = ROOT / "data" / "golden"
EVALS_DIR = GOLDEN_DIR / "evals"
VERBATIM = 0.9


def cache_key(video_id: str, sha: str, version: ExtractorVersion) -> str:
    return f"{video_id}:{sha[:12]}:{version.name}:{version.fingerprint}"


def split_for(year_bucket: str | None) -> str:
    """train / test / holdout by window year: the last window year is the sealed
    holdout, the one before it the test year, everything earlier train."""
    if not year_bucket:
        return "train"
    start = int(year_bucket[:4])
    last = settings().until.year - 1
    return "holdout" if start >= last else "test" if start == last - 1 else "train"


def _video_row(con: duckdb.DuckDBPyConnection, video_id: str) -> dict[str, Any] | None:
    r = con.execute(
        "SELECT video_id, title, description, published_at, primary_ticker, year_bucket FROM vi.videos WHERE video_id = ?",
        [video_id],
    ).fetchone()
    if not r:
        return None
    return dict(zip(["video_id", "title", "description", "t0", "ticker", "year_bucket"], r))


def _model_calls(
    t: Transcript, row: dict[str, Any], version: ExtractorVersion, critic: bool
) -> tuple[GoldenEvalDraft, dict[str, Any], Critic | None, dict[str, Any], list[float]]:
    draft, usage = run_extract(t, row["ticker"], str(row["t0"]), row.get("description"), version)
    crit, cusage, scores = (None, {}, [])
    if critic:
        crit, cusage, scores = run_critic(draft, t, model=version.critic_model)
    else:
        from value_invest.golden.critic import quote_scores

        scores = quote_scores(draft, t)
    return draft, usage, crit, cusage, scores


def assemble(
    con: duckdb.DuckDBPyConnection,
    row: dict[str, Any],
    t: Transcript,
    draft: GoldenEvalDraft,
    usage: dict[str, Any],
    crit: Critic | None,
    cusage: dict[str, Any],
    scores: list[float],
    version: ExtractorVersion,
) -> GoldenEval:
    _, g = ground(con, draft, row["ticker"], row["t0"])
    checks = g["checks"]
    checks["quote_scores"] = [round(s, 3) for s in scores]
    checks["faithful_share"] = round(sum(s >= VERBATIM for s in scores) / max(1, len(scores)), 3)
    stance = draft.call.stance_detail
    pos = position_for(stance)
    hurdle = hurdle_for(draft.call.expected_return_pct, stance)
    return GoldenEval(
        video_id=row["video_id"],
        ticker=row["ticker"],
        t0=row["t0"],
        title=row["title"],
        position=pos,
        binary_position=binary_for(stance),
        hurdle_position=hurdle,
        rule_sensitive=bool(hurdle is not None and (hurdle == "BUY") != (pos == "BUY")),
        title_says_buy=title_says_buy(row["title"]),
        call=draft.call,
        valuation=draft.valuation,
        iv_recomputed=g["iv_recomputed"],
        price_at_t0=checks.get("price_at_t0"),
        reasons=draft.reasons,
        external_facts_used=draft.external_facts_used,
        critic=crit,
        checks=checks,
        split=split_for(row.get("year_bucket")),
        provenance=Provenance(
            extractor_version=version.name,
            model=str(usage.get("model") or resolve_model(version.model)),
            session_id=usage.get("session_id"),
            transcript_sha256=t.sha256,
            extracted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            critic_model=str(cusage.get("model")) if cusage else None,
            critic_session_id=cusage.get("session_id") if cusage else None,
        ),
    )


def upsert_eval(con: duckdb.DuckDBPyConnection, ev: GoldenEval) -> None:
    j = lambda x: json.dumps(x, default=str)  # noqa: E731
    con.execute(
        """INSERT OR REPLACE INTO vi.evals (video_id, ticker, t0, position, stance_detail, personal_action,
             expected_return_pct, horizon_years, conviction, rule_sensitive, title_says_buy, headline_quote,
             valuation, iv_weighted_stated, iv_recomputed, price_mentioned, price_at_t0, reasons, external_facts,
             critic, checks, extractor_version, model, session_id, transcript_sha256, split, curation_status,
             review_note, reviewed_at, extracted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   coalesce((SELECT curation_status FROM vi.evals WHERE video_id = ?), 'auto'),
                   (SELECT review_note FROM vi.evals WHERE video_id = ?),
                   (SELECT reviewed_at FROM vi.evals WHERE video_id = ?), ?)""",
        [
            ev.video_id,
            ev.ticker,
            ev.t0,
            ev.position,
            ev.call.stance_detail,
            ev.call.personal_action,
            ev.call.expected_return_pct,
            ev.call.horizon_years,
            ev.call.conviction,
            ev.rule_sensitive,
            ev.title_says_buy,
            ev.call.headline_quote,
            j(ev.valuation.model_dump()),
            ev.valuation.iv_weighted_stated,
            j(ev.iv_recomputed),
            ev.valuation.price_mentioned,
            ev.price_at_t0,
            j([r.model_dump() for r in ev.reasons]),
            j(ev.external_facts_used),
            j(ev.critic.model_dump()) if ev.critic else None,
            j(ev.checks),
            ev.provenance.extractor_version,
            ev.provenance.model,
            ev.provenance.session_id,
            ev.provenance.transcript_sha256,
            ev.split,
            ev.video_id,
            ev.video_id,
            ev.video_id,
            datetime.now(timezone.utc),
        ],
    )


def _cache_path(video_id: str):
    EVALS_DIR.mkdir(parents=True, exist_ok=True)
    return EVALS_DIR / f"{video_id}.json"


def load_cached(video_id: str, key: str) -> GoldenEval | None:
    p = _cache_path(video_id)
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    if d.get("key") != key:
        return None
    return GoldenEval.model_validate(d["eval"])


def process_all(
    con: duckdb.DuckDBPyConnection,
    version_name: str = "v0",
    only: list[str] | None = None,
    force: bool = False,
    workers: int = 3,
    critic: bool = True,
) -> dict[str, Any]:
    version = load_version(version_name)
    ids = only or [
        r[0]
        for r in con.execute(
            "SELECT video_id FROM vi.videos WHERE in_sample AND transcript_status = 'indexed' ORDER BY published_at"
        ).fetchall()
    ]
    report: dict[str, Any] = {
        "version": version.name,
        "fingerprint": version.fingerprint,
        "cached": 0,
        "extracted": 0,
        "failed": [],
        "sdk_calls": 0,
        "tokens": 0,
    }
    todo: list[tuple[dict[str, Any], Transcript, str]] = []
    for vid in ids:
        row = _video_row(con, vid)
        if not row or not row["ticker"] or not row["t0"]:
            report["failed"].append(f"{vid}: no ticker/date")
            continue
        t = load_transcript(vid)
        if t is None:
            report["failed"].append(f"{vid}: no transcript")
            continue
        key = cache_key(vid, t.sha256, version)
        cached = None if force else load_cached(vid, key)
        if cached is not None:
            upsert_eval(con, cached)
            report["cached"] += 1
            continue
        todo.append((row, t, key))

    def work(item):
        row, t, key = item
        try:
            return item, _model_calls(t, row, version, critic), None
        except Exception as e:  # noqa: BLE001 — one failed video is reported, the batch continues
            return item, None, f"{type(e).__name__}: {str(e)[:160]}"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for (row, t, key), result, err in pool.map(work, todo):
            if err or result is None:
                report["failed"].append(f"{row['video_id']}: {err}")
                print(f"  {row['ticker']:6} {row['t0']}  FAILED {err}", flush=True)
                continue
            draft, usage, crit, cusage, scores = result
            ev = assemble(con, row, t, draft, usage, crit, cusage, scores, version)
            _cache_path(ev.video_id).write_text(
                json.dumps(
                    {
                        "key": key,
                        "eval": ev.model_dump(mode="json"),
                        "usage": {"extract": usage, "critic": cusage},
                    },
                    indent=1,
                    default=str,
                )
            )
            upsert_eval(con, ev)
            report["extracted"] += 1
            report["sdk_calls"] += 1 + int(bool(cusage))
            for u in (usage, cusage):
                report["tokens"] += int(u.get("input_tokens", 0)) + int(u.get("output_tokens", 0))
            agree = (
                ""
                if not crit
                else ("✓" if crit.position_agrees else "✗ critic " + crit.own_stance_detail)
            )
            print(
                f"  {row['ticker']:6} {row['t0']}  {ev.position:4} {ev.call.stance_detail:13} iv={ev.valuation.iv_weighted_stated} repro={ev.checks['reproducible_share']} faithful={ev.checks['faithful_share']} {agree}",
                flush=True,
            )
    report["in_evals"] = con.execute("SELECT count(*) FROM vi.evals").fetchone()[0]
    return report


# ---------------------------------------------------------------- seed eval, κ, summary


def _evals(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    cur = con.execute("SELECT * FROM vi.evals ORDER BY t0")
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        for k in ("valuation", "iv_recomputed", "reasons", "external_facts", "critic", "checks"):
            d[k] = json.loads(d[k]) if d.get(k) else None
        out.append(d)
    return out


def seed_eval(con: duckdb.DuckDBPyConnection, version_name: str = "v0") -> dict[str, Any]:
    seed = json.loads((GOLDEN_DIR / "seed_labels.json").read_text())["labels"]
    by_id = {e["video_id"]: e for e in _evals(con)}
    rows = []
    for s in seed:
        e = by_id.get(s["video_id"])
        if not e:
            continue
        seed_pos = THREE_WAY[s["stance_detail"]]
        matched = 0
        for sr in s.get("reasons", []):
            if any(
                r["category"] == sr["category"] and r["direction"] == sr["direction"]
                for r in e["reasons"]
            ):
                matched += 1
        rows.append(
            {
                "video_id": s["video_id"],
                "ticker": s["ticker"],
                "read": s["read"],
                "seed_stance": s["stance_detail"],
                "eval_stance": e["stance_detail"],
                "seed_position": seed_pos,
                "eval_position": e["position"],
                "position_ok": seed_pos == e["position"],
                "stance_ok": s["stance_detail"] == e["stance_detail"],
                "seed_reasons": len(s.get("reasons", [])),
                "reasons_matched": matched,
                "iv_stated_seed": s.get("iv_stated"),
                "iv_stated_eval": e.get("iv_weighted_stated"),
                "faithful_share": (e["checks"] or {}).get("faithful_share"),
            }
        )

    def acc(rs, key):
        return round(sum(r[key] for r in rs) / len(rs), 3) if rs else None

    def balanced(rs):
        per = {}
        for cls in ("BUY", "HOLD", "SELL"):
            sub = [r for r in rs if r["seed_position"] == cls]
            per[cls] = {"n": len(sub), "recall": acc(sub, "position_ok")}
        vals = [p["recall"] for p in per.values() if p["recall"] is not None]
        return {
            "per_class": per,
            "balanced_accuracy": round(sum(vals) / len(vals), 3) if vals else None,
        }

    full = [r for r in rows if r["read"] == "full"]
    with_reasons = [r for r in rows if r["seed_reasons"]]
    result = {
        "version": version_name,
        "n_seed": len(seed),
        "n_scored": len(rows),
        "n_full": len(full),
        "position_accuracy_full": acc(full, "position_ok"),
        "stance_accuracy_full": acc(full, "stance_ok"),
        "position_accuracy_all": acc(rows, "position_ok"),
        "stance_accuracy_all": acc(rows, "stance_ok"),
        "balanced_full": balanced(full),
        "balanced_all": balanced(rows),
        "reason_recall": round(
            sum(r["reasons_matched"] for r in with_reasons)
            / max(1, sum(r["seed_reasons"] for r in with_reasons)),
            3,
        )
        if with_reasons
        else None,
        "faithful_share_mean": round(
            statistics.mean([r["faithful_share"] for r in rows if r["faithful_share"] is not None]),
            3,
        )
        if rows
        else None,
        "disagreements": [r for r in rows if not r["position_ok"] or not r["stance_ok"]],
        "rows": rows,
    }
    (GOLDEN_DIR / f"seed_eval_{version_name}.json").write_text(
        json.dumps(result, indent=1, default=str)
    )
    return {k: v for k, v in result.items() if k != "rows"}


def kappa(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    pairs = [
        (e["stance_detail"], e["critic"]["own_stance_detail"])
        for e in _evals(con)
        if e.get("critic")
    ]
    rep = kappa_report(pairs)
    (GOLDEN_DIR / "kappa.json").write_text(json.dumps(rep, indent=1))
    return rep


def method_summary(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """What the 40 (→ 120) evals say about how he values: the distilled parameters."""
    evals = _evals(con)
    disc: Counter = Counter()
    base_names: Counter = Counter()
    methods: Counter = Counter()
    terminal: dict[str, list[float]] = defaultdict(list)
    terminal_by_growth: dict[str, list[float]] = defaultdict(list)
    probs: dict[str, list[float]] = defaultdict(list)
    growth: dict[str, list[float]] = defaultdict(list)
    cats: dict[str, Counter] = {"for_buy": Counter(), "for_sell": Counter()}
    feeds: Counter = Counter()
    repro_by_cat: dict[str, Counter] = defaultdict(Counter)
    er_by_stance: dict[str, list[float]] = defaultdict(list)
    stance_mix: Counter = Counter()
    position_mix: Counter = Counter()
    for e in evals:
        v = e["valuation"] or {}
        methods[v.get("method", "none")] += 1
        if v.get("discount_rate") is not None:
            disc[f"{round(v['discount_rate'] * 100)} %"] += 1
        if v.get("base_metric"):
            base_names[v["base_metric"].get("name")] += 1
        for s in v.get("scenarios", []):
            if s.get("terminal_multiple") is not None:
                terminal[s["name"]].append(s["terminal_multiple"])
                g = s.get("g_y1_5")
                if g is not None:
                    bucket = (
                        "<5 %"
                        if g < 0.05
                        else "5–10 %"
                        if g < 0.10
                        else "10–20 %"
                        if g < 0.20
                        else "≥20 %"
                    )
                    terminal_by_growth[bucket].append(s["terminal_multiple"])
            if s.get("probability") is not None:
                probs[s["name"]].append(s["probability"])
            if s.get("g_y1_5") is not None:
                growth[s["name"]].append(s["g_y1_5"])
        for r in e["reasons"] or []:
            cats[r["direction"]][r["category"]] += 1
            feeds[r.get("feeds", "none")] += 1
            if r.get("data_check"):
                repro_by_cat[r["category"]][r["data_check"]["reproducible"]] += 1
        if e.get("expected_return_pct") is not None:
            er_by_stance[e["stance_detail"]].append(e["expected_return_pct"])
        stance_mix[e["stance_detail"]] += 1
        position_mix[e["position"]] += 1

    def stats(xs: list[float]) -> dict[str, Any] | None:
        if not xs:
            return None
        return {
            "n": len(xs),
            "median": round(statistics.median(xs), 3),
            "min": min(xs),
            "max": max(xs),
        }

    out = {
        "n_evals": len(evals),
        "position_mix": dict(position_mix),
        "stance_mix": dict(stance_mix),
        "methods": dict(methods),
        "base_metric": dict(base_names),
        "discount_rate": dict(disc),
        "growth_y1_5": {k: stats(v) for k, v in growth.items()},
        "terminal_multiple": {k: stats(v) for k, v in terminal.items()},
        "terminal_multiple_by_growth_bucket": {k: stats(v) for k, v in terminal_by_growth.items()},
        "scenario_probability": {k: stats(v) for k, v in probs.items()},
        "expected_return_by_stance": {k: stats(v) for k, v in er_by_stance.items()},
        "reason_categories": {k: dict(c.most_common()) for k, c in cats.items()},
        "reason_feeds": dict(feeds.most_common()),
        "reproducible_by_category": {k: dict(c) for k, c in repro_by_cat.items()},
        "reproducible_share": round(
            sum((e["checks"] or {}).get("reproducible_share", 0) for e in evals)
            / max(1, len(evals)),
            3,
        ),
        "base_metric_gap_over_15pct": sum(
            1 for e in evals if abs(((e["checks"] or {}).get("base_metric_gap_pct") or 0)) > 15
        ),
        "generated_at": date.today().isoformat(),
    }
    (GOLDEN_DIR / "method_summary.json").write_text(json.dumps(out, indent=1, default=str))
    return out
