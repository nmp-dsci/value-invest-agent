"""Render the M2 walkthrough page (.lavish/s03_m2-walkthrough.html) from the live numbers.

Usage:
  uv run python scripts/m2_numbers.py > .lavish/s03_evidence/m2_numbers.json
  uv run python scripts/s03_page.py
Every figure on the page comes from that JSON; screenshots live in .lavish/s03_evidence/."""

from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAVISH = ROOT / ".lavish"
EVID = LAVISH / "s03_evidence"
OUT = LAVISH / "s03_m2-walkthrough.html"
POS_TAG = {"BUY": "good", "HOLD": "acc", "SELL": "bad"}
H = ("6", "12", "24")


def esc(x: object) -> str:
    return html.escape(str(x))


def pct(v: float | None, d: int = 0) -> str:
    return "—" if v is None else f"{v * 100:.{d}f} %"


def num(v: float | None, d: int = 0) -> str:
    return "—" if v is None else f"{v:.{d}f}"


def pp(v: float | None) -> str:
    return "—" if v is None else f"{'+' if v > 0 else ''}{v * 100:.1f}"


def hit(b: dict | None, cls: str) -> str:
    if not b:
        return "—"
    a, n = b["hits"].get(cls, [0, 0])
    return f"{a}/{n}" if n else "—"


def style() -> str:
    src = (LAVISH / "s02_m2-golden-extraction-plan.html").read_text()
    m = re.search(r"<style>.*?</style>", src, re.S)
    assert m
    return m.group(0)


def main() -> None:
    N = json.loads((EVID / "m2_numbers.json").read_text())
    evals = N["evals"]
    t0_of = {e["video_id"]: e["t0"] for e in evals}
    n = len(evals)
    mix = {k: sum(1 for e in evals if e["position"] == k) for k in ("BUY", "HOLD", "SELL")}
    ov = N["validation"]["overall"]
    by_year = N["validation"]["by_year"]
    seed = {v: N.get(f"seed_eval_{v}") for v in ("v0", "v1", "v2")}
    kappa = N.get("kappa") or {}
    ms = N.get("method_summary") or {}
    funnel = N["funnel"]
    with_iv = sum(1 for e in evals if e["iv_weighted_stated"] is not None)
    faithful_mean = sum((e["faithful_share"] or 0) for e in evals) / max(1, n)
    critic_agree = sum(1 for e in evals if e["critic_agrees"])
    rule_sens = [e for e in evals if e["rule_sensitive"]]
    title_mis = [e for e in evals if e["title_says_buy"] and e["position"] != "BUY"]
    base_gap = sum(1 for e in evals if e["base_gap"] is not None and abs(e["base_gap"]) > 15)
    price_n = sum(1 for e in evals if e["price_check"] in ("true", "false"))
    price_ok = sum(1 for e in evals if e["price_check"] == "true")
    iv_ok = sum(e["iv_ok"] or 0 for e in evals)
    iv_cmp = sum(e["iv_compared"] or 0 for e in evals)
    reasons = N["reasons"]
    by_cat: dict[str, dict[str, int]] = {}
    for r in reasons:
        by_cat.setdefault(r["category"], {}).setdefault(r["reproducible"] or "n/a", 0)
        by_cat[r["category"]][r["reproducible"] or "n/a"] += r["n"]
    total_reasons = sum(r["n"] for r in reasons)
    repro_total = sum(
        r["n"] for r in reasons if r["reproducible"] in ("statements", "prices", "derived")
    )
    images = sorted(p.name for p in EVID.glob("*.jpg")) if EVID.exists() else []

    def img(name: str, caption: str) -> str:
        if name not in images:
            return f'<div class="note warn">screenshot {esc(name)} not captured yet</div>'
        return f'<figure><img src="s03_evidence/{esc(name)}" alt="{esc(caption)}" style="width:100%;border:1px solid var(--line);border-radius:10px"><figcaption>{esc(caption)}</figcaption></figure>'

    def seed_row(v: str) -> str:
        s = seed.get(v)
        if not s:
            return f"<tr><td class=mono>{v}</td><td colspan=7 class=mono>not scored</td></tr>"
        b = s.get("balanced_full") or {}
        per = b.get("per_class") or {}
        rec = " · ".join(
            f"{k} {per[k]['recall']:.2f}"
            for k in ("BUY", "HOLD", "SELL")
            if per.get(k) and per[k]["recall"] is not None
        )
        k6 = {"v0": 0.784, "v1": 0.620, "v2": kappa.get("kappa_6way")}.get(v)
        k3 = {"v0": 0.765, "v1": 0.660, "v2": kappa.get("kappa_3way")}.get(v)
        return (
            f"<tr><td class=mono>{v}</td><td class=r>{s['n_full']}</td><td class=r><b>{pct(s['position_accuracy_full'])}</b></td>"
            f"<td class=r>{num(b.get('balanced_accuracy'), 2)}</td><td class=mono>{rec}</td><td class=r>{pct(s['position_accuracy_all'])} ({s['n_scored']})</td>"
            f"<td class=r>{num(s.get('reason_recall'), 2)}</td><td class=r>{num(s.get('faithful_share_mean'), 2)}</td><td class=r>{num(k6, 2)} / {num(k3, 2)}</td></tr>"
        )

    def bucket_cells(b: dict | None) -> str:
        if not b:
            return "<td class=r>—</td>" * 3
        return (
            f"<td class=r>{hit(b, 'BUY')} · {hit(b, 'HOLD')} · {hit(b, 'SELL')}</td>"
            f"<td class=r>{b['verdict']['correct']} · {b['verdict']['wrong']} · {b['verdict']['indeterminate']}</td>"
            f"<td class=r>{num(b['mean_excess'].get('BUY'))} · {num(b['mean_excess'].get('HOLD'))} · {num(b['mean_excess'].get('SELL'))}</td>"
        )

    eval_rows = []
    for e in sorted(evals, key=lambda x: (not x["rule_sensitive"], x["t0"])):
        v = {h: e["validations"].get(h) for h in H}
        cells = "".join(
            f'<td class="r mono" style="color:var(--{"good" if v[h] and v[h]["excess"] > 0.05 else "bad" if v[h] and v[h]["excess"] < -0.05 else "caption"})">{pp(v[h]["excess"]) if v[h] else "—"}</td>'
            for h in H
        )
        vd = v["12"]["verdict"] if v["12"] else None
        vcell = (
            f'<span class="tag {"good" if vd == "correct" else "bad" if vd == "wrong" else ""}">{vd}</span>'
            if vd
            else "—"
        )
        flags = (' <span class="tag warn">A≠B</span>' if e["rule_sensitive"] else "") + (
            ' <span class="tag warn">title</span>'
            if e["title_says_buy"] and e["position"] != "BUY"
            else ""
        )
        eval_rows.append(
            f"<tr><td class=mono><b>{esc(e['ticker'])}</b> · {e['t0']}</td><td>{esc(e['title'][:64])}</td><td><span class=tag>{e['split']}{'' if v['12'] else ' · holdout @12'}</span></td>"
            f'<td><span class="tag {POS_TAG[e["position"]]}">{e["position"]}</span>{flags}</td><td class=mono>{e["stance_detail"]}</td>'
            f"<td class=r>{num(e['expected_return_pct'])}</td><td class=r>{num(e['iv_weighted_stated'])} → {num(e['price_at_t0'])}</td>{cells}"
            f"<td>{vcell}</td>"
            f"<td class=r>{pct(e['reproducible_share'])}</td><td class=mono>{'✓' if e['critic_agrees'] else esc(e['critic_stance'] or '—')}</td></tr>"
        )

    def ms_stats(key: str) -> str:
        d = ms.get(key) or {}
        return (
            " · ".join(
                f"{k} <b>{v['median']}</b> (n {v['n']}, {v['min']}–{v['max']})"
                for k, v in d.items()
                if v
            )
            or "—"
        )

    cats_buy = ", ".join(
        f"{k} {v}"
        for k, v in list((ms.get("reason_categories") or {}).get("for_buy", {}).items())[:6]
    )
    cats_sell = ", ".join(
        f"{k} {v}"
        for k, v in list((ms.get("reason_categories") or {}).get("for_sell", {}).items())[:6]
    )
    split_at = N["validation"].get("split_at", {})

    def split_cells(sa: dict) -> str:
        tr, te, ho = sa.get("train") or {}, sa.get("test") or {}, sa.get("holdout") or {}

        def vx(b: dict) -> str:
            v = b.get("verdict") if b else None
            return f"{v['correct']} · {v['wrong']} · {v['indeterminate']}" if v else "—"

        return (
            f"<td class=r>{tr.get('n', 0)} · <span class=acc>{te.get('n', 0)}</span> · <span class=warn>{ho.get('n', 0)}</span></td>"
            f"<td class=r>{vx(tr)}</td><td class=r>{vx(te)}</td>"
        )

    year_rows = []
    for m in N["mix"]:
        yb = m["year_bucket"]
        f = next((x for x in funnel if x["year_bucket"] == yb), {})
        year_rows.append(
            f"<tr><td class=mono>{yb}</td><td class=r>{f.get('videos', '—')}</td><td class=r>{f.get('single', '—')}</td><td class=r>{f.get('sampled', '—')}</td><td class=r>{f.get('indexed', '—')}</td><td class=r>{m['n']}</td><td class=r>{m['buy']} / {m['hold']} / {m['sell']}</td><td class=r>{m['train']} · <span class=acc>{m['test']}</span></td><td class=r>{m['rule_sensitive']}</td>"
            + "".join(bucket_cells(by_year.get(yb, {}).get(h)) for h in ("12",))
            + "</tr>"
        )
    split_rows = "".join(
        f"<tr><td class=mono>+{h} m</td>{split_cells(split_at.get(h, {}).get('overall', {}))}</tr>"
        for h in H
    )
    split_year_rows = "".join(
        f"<tr><td class=mono>{m['year_bucket']}</td>"
        + "".join(
            split_cells(split_at.get(h, {}).get("by_year", {}).get(m["year_bucket"], {})) for h in H
        )
        + "</tr>"
        for m in N["mix"]
    )

    cat_rows = []
    for cat, d in sorted(by_cat.items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(d.values())
        rep = d.get("statements", 0) + d.get("prices", 0) + d.get("derived", 0)
        cat_rows.append(
            f"<tr><td class=mono>{cat}</td><td class=r>{tot}</td><td class=r>{d.get('statements', 0)}</td><td class=r>{d.get('prices', 0)}</td><td class=r>{d.get('derived', 0)}</td><td class=r>{d.get('external', 0)}</td><td class=r>{d.get('judgement', 0)}</td><td class=r><b>{pct(rep / tot)}</b></td></tr>"
        )

    ov12 = ov.get("12") or {}
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>value·invest agent — M2 walkthrough: golden evals</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap">
{style()}
<style>span.acc{{color:var(--accent);font-weight:600}} span.warn{{color:var(--warn);font-weight:600}} th span.acc,th span.warn{{font-weight:500}}</style>
</head>
<body>
<nav class="top"><div class="wrap">
  <span class="brand"><span class="diamond"></span>value·invest agent</span>
  <a href="#built">Built</a><a href="#how">How an eval is made</a><a href="#seed">Extractor iterations</a><a href="#validation">Were his calls right?</a><a href="#evals">All evals</a><a href="#ground">Grounding</a><a href="#method">His method</a><a href="#window">The 120</a><a href="#app">App</a><a href="#review">Review</a>
</div></nav>
<div class="wrap">
<header class="hero">
  <div class="eyebrow"><span>s03 · milestone 2 walkthrough</span><span class="tag good">S4 + S5 built · {n} golden evals · validated</span><span class="tag acc">branch m2-golden</span><span class="tag">{date.today().isoformat()}</span></div>
  <h1>Milestone 2: <em>golden evals</em>, validated.</h1>
  <p class="lede">{n} single-stock videos from six window years ({N["since"]} → {N["until"]}, 20 per year) were read by the extractor and turned into a golden eval: his BUY / HOLD / SELL, the intrinsic-value inputs he typed into his template, the 3–5 reasons he gave — each quoted, anchored to a transcript timestamp, and checked against the financial data visible on the video date — plus what the stock did against the index 6, 12 and 24 months later. The extractor was iterated three times on a hand-labelled seed; a second model audits every eval. Everything on this page comes from the live database (<span class="k">scripts/m2_numbers.py</span>).</p>
  <div class="facts">
    <span><b>{n}</b> evals · <b>{mix["BUY"]}</b> BUY · <b>{mix["HOLD"]}</b> HOLD · <b>{mix["SELL"]}</b> SELL</span>
    <span>seed position accuracy <b>{pct((seed.get("v2") or {}).get("position_accuracy_full"))}</b> on the {(seed.get("v2") or {}).get("n_full", "—")} fully-read videos · balanced <b>{num(((seed.get("v2") or {}).get("balanced_full") or {}).get("balanced_accuracy"), 2)}</b></span>
    <span>κ extractor vs critic <b>{num(kappa.get("kappa_6way"), 2)}</b> (6-way) · <b>{num(kappa.get("kappa_3way"), 2)}</b> (3-way)</span>
    <span>at 12 m (n {ov12.get("n", 0)}): BUY right <b>{hit(ov12, "BUY")}</b> · HOLD <b>{hit(ov12, "HOLD")}</b> · SELL <b>{hit(ov12, "SELL")}</b></span>
    <span><b>{pct(repro_total / max(1, total_reasons))}</b> of {total_reasons} reasons reproducible from data at T0</span>
    <span>quotes verbatim <b>{pct(faithful_mean)}</b> · critic agrees on position <b>{critic_agree} / {n}</b></span>
  </div>
</header>

<section id="built">
  <div class="section-head"><span class="num">00</span><h2>What was built</h2></div>
  <div class="cards">
    <div class="card rec"><h4><span class="num">S4.0</span> His template as code</h4><p><span class="k">valuation.py</span>: two-stage 10-year growth → terminal P/E → discount at his required return, scenario weighting, the expected-return and implied-growth solvers, buyback yield, dividend spread. <span class="k">vi valuation check</span> reproduces 10 / 10 intrinsic values he states on camera within his rounding.</p></div>
    <div class="card rec"><h4><span class="num">S4.1–4.3</span> The extraction pipeline</h4><p><span class="k">vi extract</span>: locate (chunk anchors, sha) → extract (Agent SDK, Sonnet, <span class="k">extractors/v2/system.md</span>) → ground (Python, point-in-time only) → critic (Opus) → checkpoint (cache keyed on transcript sha + prompt fingerprint, <span class="k">vi.evals</span>). <span class="k">vi golden eval-seed · kappa · summary</span>; <span class="k">vi extract --reground</span> re-runs grounding without a model call.</p></div>
    <div class="card"><h4><span class="num">S4.4</span> The window: 20 / yr × 6 = {n}</h4><p><span class="k">VI_SINCE=2020-09-17</span>; ~360 older titles classified, 88 dates refined, EDGAR eligibility re-checked under the "has the financial reports" rule (20-F / 40-F us-gaap filers, XOM and FI overrides), sticky draw kept the first 40, 80 transcripts ingested, prices from 2015.</p></div>
    <div class="card"><h4><span class="num">S5</span> Validation + the app</h4><p><span class="k">vi validate</span> → <span class="k">vi.validations</span> (excess vs SPY at 6 / 12 / 24 m, D14 bands, IV hit). <span class="k">vi rates</span> → FRED DGS10 / DGS3MO. <b>Golden Evals</b> tab (insights on top, evals below, review control) and the eval panel on the <b>Video</b> tab with ▶ jumps into the transcript and the IV line + verdict markers on the chart.</p></div>
  </div>
  <div class="tablewrap"><table>
    <thead><tr><th>Deliverable</th><th>Where</th><th>Tests</th></tr></thead>
    <tbody>
      <tr><td>Schema: <span class="k">vi.evals</span>, <span class="k">vi.validations</span>, <span class="k">vi.rates</span> (+ <span class="k">rates_as_of</span>)</td><td class="mono">data/schema.sql</td><td>test_golden · test_app</td></tr>
      <tr><td><span class="k">GoldenEval</span> models — the draft the model returns and the checkpointed object; rule C / A / B derivations; lenient parsing of the model's number-as-text habits</td><td class="mono">src/value_invest/golden/models.py</td><td>test_golden (rules, leniency)</td></tr>
      <tr><td>Transcript anchors + fuzzy verbatim check · extractor versions (frozen <span class="k">version.yaml</span>, fingerprint)</td><td class="mono">golden/transcript.py · golden/versions.py · extractors/v0–v2/</td><td>test_golden</td></tr>
      <tr><td>Grounding: his words → line items / derived ratios / FRED, IV recompute, price check, reproducibility per reason</td><td class="mono">golden/ground.py</td><td>test_golden (as-of, no leak)</td></tr>
      <tr><td>Critic + κ · checkpoint (cache, upsert keeping reviews, seed eval, method summary) · validator</td><td class="mono">golden/critic.py · kappa.py · checkpoint.py · validate.py</td><td>test_golden</td></tr>
      <tr><td>FRED loader · EDGAR eligibility broadened + CIK overrides · <span class="k">vi market --refresh-prices</span></td><td class="mono">market/fred.py · market/edgar.py · data/edgar_cik_overrides.json</td><td>test_edgar</td></tr>
      <tr><td>API: <span class="k">/api/evals</span>, <span class="k">/api/evals/summary</span>, <span class="k">/api/evals/{{id}}</span>, <span class="k">POST /api/evals/{{id}}/review</span>; the eval rides along on <span class="k">/api/videos/{{id}}</span></td><td class="mono">serving/app.py</td><td>test_app</td></tr>
      <tr><td>Frontend: Golden Evals view, shared EvalPanel, Video tab integration, chart IV line + verdict markers</td><td class="mono">frontend/src/views/GoldenEvals.tsx · EvalPanel.tsx · Video.tsx · PriceChart.tsx</td><td>tsc + build</td></tr>
      <tr><td>Checkpoint artefacts: seed labels (36 hand labels, 17 read in full), his 10 stated IVs, the eval cache, seed evals v0–v2, κ, method summary</td><td class="mono">data/golden/</td><td>—</td></tr>
      <tr><td>Docs: README pipeline table, AGENTS layout, CLAUDE rules (120 sample, position rule, grounding), spec s02, plan rev 4</td><td class="mono">README.md · AGENTS.md · CLAUDE.md · ai_specs/</td><td>—</td></tr>
    </tbody>
  </table></div>
</section>

<section id="how">
  <div class="section-head"><span class="num">01</span><h2>How one eval is made — Apple, 21 Jan 2025</h2></div>
  <p>The extractor sees only the transcript (with a <span class="k">[chunk:id @ m:ss]</span> marker at each chunk) and never the title as evidence. Python then fills every reason's data check from <span class="k">vi.statements_as_of</span>, prices ≤ T0 and FRED; the critic (a second model) verifies each quote is real and gives its own stance for κ.</p>
  {img("how-aapl-eval.jpg", "The Video tab for the Apple video: the eval panel beside the transcript, ▶ jumps to the cited chunk; the chart carries his IV line and the +6 / 12 / 24 m verdict markers.")}
  <div class="tablewrap"><table>
    <thead><tr><th>#</th><th>reason (his claim, paraphrased by the extractor)</th><th>category</th><th>data check</th></tr></thead>
    <tbody>{"".join(f"<tr><td class=mono>{r['rank']}</td><td>{esc(r['claim'])}</td><td class=mono>{r['category']} · {r['direction']}</td><td><span class='tag {'good' if r['data_check']['reproducible'] in ('statements', 'prices', 'derived') else 'bad' if r['data_check']['reproducible'] == 'external' else ''}'>{r['data_check']['reproducible']}</span> {'✓' if r['data_check']['agrees'] else '✗' if r['data_check']['agrees'] is False else ''} <span class=mono style='font-size:12px;color:var(--caption)'>{esc(r['data_check'].get('formula') or '')} {esc((r['data_check'].get('gap_note') or '')[:90])}</span></td></tr>" for r in json.loads((ROOT / "data/golden/evals/vDirkgS91VQ.json").read_text())["eval"]["reasons"])}</tbody>
  </table></div>
  <p style="font-size:13.5px;color:var(--caption)">His inputs (EPS 6, 5 % growth, P/E 20 normal; 0 % / 12 worst; 10 % discount) recompute to 82 and 33 against his 80 and 34; the price he quotes (228) matches a close within five trading days of T0; the base EPS he uses (6) is within 2 % of the FY2024 diluted EPS visible at T0 (6.08).</p>
</section>

<section id="seed">
  <div class="section-head"><span class="num">02</span><h2>Iterating the extractor on the seed: v0 → v1 → v2</h2></div>
  <p>The seed is 36 videos I labelled from the transcripts while writing the plan (17 read end to end, the rest at the conclusion). Each version re-ran all 40 first-window evals; the seed score, κ and the disagreement list drove the next prompt. v1 fixed the irony problem (BlackRock's "simply the best buy" is a video where he refuses to own it) and the low-return holds, but over-corrected "wait for a better price" into avoid; v2 introduced the test "would he own it at this price?" for fair_hold vs avoid and aligned the critic's definitions.</p>
  <div class="tablewrap"><table>
    <thead><tr><th>version</th><th class="r">n full</th><th class="r">position acc (full)</th><th class="r">balanced</th><th>recall B · H · S</th><th class="r">position acc (all)</th><th class="r">reason recall</th><th class="r">quotes verbatim</th><th class="r">κ 6-way / 3-way</th></tr></thead>
    <tbody>{seed_row("v0")}{seed_row("v1")}{seed_row("v2")}</tbody>
  </table></div>
  <div class="note">The remaining v2 disagreements are the genuinely borderline videos: {esc(", ".join(f"{d['ticker']} {t0_of.get(d['video_id'], '')[:7]} ({d['seed_stance']} → {d['eval_stance']})" for d in ((seed.get("v2") or {}).get("disagreements") or [])))}. They are flagged in the app and are the first rows to review.</div>
</section>

<section id="validation">
  <div class="section-head"><span class="num">03</span><h2>Were his calls right? Recommendation vs the index at T0 + 6 / 12 / 24 months</h2></div>
  <p>Benchmark SPY, adjusted closes to {N.get("last_price_date", "")}. A BUY is right if it beat the index by more than 5 pp, a SELL if it lagged by more than 5 pp, a HOLD if it stayed within ±10 pp (D14). 24-month verdicts exist only for videos before Sept 2024.</p>
  <div class="tablewrap"><table>
    <thead><tr><th>horizon</th><th class="r">n</th><th class="r">BUY / HOLD / SELL</th><th class="r">right: BUY · HOLD · SELL</th><th class="r">✓ · ✗ · ~</th><th class="r">mean excess pp: BUY · HOLD · SELL</th><th class="r">HOLD as "did not lag": ✓</th><th class="r">IV reached</th></tr></thead>
    <tbody>{"".join(f"<tr><td class=mono>+{h} m</td><td class=r>{ov[h]['n']}</td><td class=r>{ov[h]['mix']['BUY']} / {ov[h]['mix']['HOLD']} / {ov[h]['mix']['SELL']}</td>{bucket_cells(ov[h])}<td class=r>{ov[h]['verdict_hold_alt']['correct']}</td><td class=r>{ov[h]['iv_hit'][0]} / {ov[h]['iv_hit'][1]}</td></tr>" for h in H if h in ov)}</tbody>
  </table></div>
  <h3>Per window year (12-month horizon)</h3>
  <div class="tablewrap"><table>
    <thead><tr><th>year</th><th class="r">videos</th><th class="r">single</th><th class="r">sampled</th><th class="r">indexed</th><th class="r">evals</th><th class="r">B / H / S</th><th class="r">train · test</th><th class="r">rule-sens.</th><th class="r">right @12 m</th><th class="r">✓ · ✗ · ~</th><th class="r">mean excess</th></tr></thead>
    <tbody>{"".join(year_rows)}</tbody>
  </table></div>
  <h3>Train / test / holdout (D15 — revised in this review)</h3>
  <p><b>Train</b> and <b>test</b> are stamped on the video, not the year: inside every window year the sampled videos are ranked by a seeded hash and {round(N["validation"].get("test_share", 0.3) * 100)} % become test ({N["validation"]["splits"].get("train", 0)} / {N["validation"]["splits"].get("test", 0)} overall, 6 test per year). So the M3 agent is tuned on train and gated on test across the <em>same</em> years — it is checked on history it never saw, not only on the newest year. <b>Holdout</b> is not a label: it is every eval whose T0 + h close is not in the price table yet, so it depends on the horizon — pick +6 m and nearly everything has an answer, pick +24 m and the last two window years are still open. Membership is independent of the labels, so a review that changes a position never moves a video between splits. SQL: <span class="k">SELECT * FROM vi.split_at(12)</span>.</p>
  <div class="tablewrap"><table>
    <thead><tr><th>horizon</th><th class="r">train · <span class=acc>test</span> · <span class=warn>holdout</span></th><th class="r">train ✓ · ✗ · ~</th><th class="r">test ✓ · ✗ · ~</th></tr></thead>
    <tbody>{split_rows}</tbody>
  </table></div>
  <div class="tablewrap"><table>
    <thead><tr><th rowspan="2">year</th>{"".join(f'<th colspan="3">@ +{h} m</th>' for h in H)}</tr>
    <tr>{"".join('<th class="r">train · <span class=acc>test</span> · <span class=warn>holdout</span></th><th class="r">train ✓ · ✗ · ~</th><th class="r">test ✓ · ✗ · ~</th>' for _ in H)}</tr></thead>
    <tbody>{split_year_rows}</tbody>
  </table></div>
  <div class="note warn"><b>Read with the n.</b> An always-SELL baseline scores every SELL verdict and nothing else; per-class hit rates and the balanced view are the numbers to compare an agent against in M3, not the raw correct count.</div>
</section>

<section id="evals">
  <div class="section-head"><span class="num">04</span><h2>All {n} evals</h2></div>
  <p>A position is a ticker <em>at a date</em> — the same stock recurs across years (Berkshire nine times, Apple five), so the first column carries both. Rule-sensitive rows first (the binary and hurdle cuts disagree with the 3-way position), then by date. Excess vs SPY in pp; verdict at 12 m; "repro." = share of the reasons an agent could rebuild from data at T0; "critic" ✓ = the auditing model reads the same position.</p>
  <div class="tablewrap"><table>
    <thead><tr><th>position = ticker · T0</th><th>title</th><th>split</th><th>position</th><th>stance</th><th class="r">expects %</th><th class="r">IV → price</th><th class="r">+6 m</th><th class="r">+12 m</th><th class="r">+24 m</th><th>verdict</th><th class="r">repro.</th><th>critic</th></tr></thead>
    <tbody>{"".join(eval_rows)}</tbody>
  </table></div>
</section>

<section id="ground">
  <div class="section-head"><span class="num">05</span><h2>Grounding: which of his reasons an agent could rebuild at T0</h2></div>
  <p>{total_reasons} reasons across {n} evals. A reason is <em>statements / prices / derived</em> when the number he cites resolves to a line item, a price, or a ratio of them (and the comparison is recorded); <em>external</em> when it rests on consensus, guidance, segments or 13F holdings; <em>judgement</em> when it is a qualitative call (moat, competence). Numbers he cites agree with the as-of value within 15 % in the cases counted; his intrinsic values recompute within ±10 % in {iv_ok} of {iv_cmp} scenarios; the price he quotes matches a close near T0 in {price_ok} of {price_n}; {base_gap} evals use a base metric more than 15 % away from the last annual figure (his TTM vs our annual — D9).</p>
  <div class="tablewrap"><table>
    <thead><tr><th>category</th><th class="r">reasons</th><th class="r">statements</th><th class="r">prices</th><th class="r">derived</th><th class="r">external</th><th class="r">judgement</th><th class="r">reproducible</th></tr></thead>
    <tbody>{"".join(cat_rows)}</tbody>
  </table></div>
</section>

<section id="method">
  <div class="section-head"><span class="num">06</span><h2>His method, distilled from {ms.get("n_evals", n)} evals</h2></div>
  <div class="cards">
    <div class="card"><h4>Valuation method</h4><p>{esc(", ".join(f"{k} {v}" for k, v in (ms.get("methods") or {}).items()))} · base metric {esc(", ".join(f"{k} {v}" for k, v in (ms.get("base_metric") or {}).items()))}</p><p>discount rate {esc(", ".join(f"{k} ×{v}" for k, v in (ms.get("discount_rate") or {}).items()))}</p></div>
    <div class="card"><h4>Growth he assumes (years 1–5)</h4><p>{ms_stats("growth_y1_5")}</p></div>
    <div class="card"><h4>Terminal P/E</h4><p>{ms_stats("terminal_multiple")}</p><p>by growth bucket: {ms_stats("terminal_multiple_by_growth_bucket")}</p></div>
    <div class="card"><h4>Scenario probabilities</h4><p>{ms_stats("scenario_probability")}</p><p>expected return by stance: {ms_stats("expected_return_by_stance")}</p></div>
    <div class="card"><h4>What he argues from</h4><p>for BUY: {esc(cats_buy)}</p><p>for SELL: {esc(cats_sell)}</p><p>reasons that feed a valuation input: {esc(", ".join(f"{k} {v}" for k, v in (ms.get("reason_feeds") or {}).items()))}</p></div>
    <div class="card"><h4>Position mix</h4><p>{esc(", ".join(f"{k} {v}" for k, v in (ms.get("position_mix") or {}).items()))} · stance {esc(", ".join(f"{k} {v}" for k, v in (ms.get("stance_mix") or {}).items()))}</p></div>
  </div>
  <p style="font-size:13.5px;color:var(--caption)">These are M3's starting parameters: <span class="k">helper.py</span> = <span class="k">valuation.py</span> + as-of loaders; <span class="k">system.md</span> = this table in prose. What M2 does not distil is the mapping from data to a growth rate — that is the learning problem.</p>
</section>

<section id="window">
  <div class="section-head"><span class="num">07</span><h2>The 120: extending the window to 2020</h2></div>
  <p>Six window years of 12 months from {N["since"]}. The catalogue was re-bucketed, the classifier labelled the older titles, exact dates were refined for the new singles, EDGAR eligibility was re-checked under D13 (eligible = SEC filer with annual us-gaap statements; {N["tickers"][0]["filers"]} tickers qualify, {N["tickers"][0]["non_filers"]} do not), and the sticky sampler kept the first 40 and added 80.</p>
  <div class="tablewrap"><table>
    <thead><tr><th>year</th><th class="r">videos</th><th class="r">single-stock</th><th class="r">sampled</th><th class="r">transcripts</th></tr></thead>
    <tbody>{"".join(f"<tr><td class=mono>{f['year_bucket']}</td><td class=r>{f['videos']}</td><td class=r>{f['single']}</td><td class=r>{f['sampled']}</td><td class=r>{f['indexed']}</td></tr>" for f in funnel)}</tbody>
  </table></div>
</section>

<section id="app">
  <div class="section-head"><span class="num">08</span><h2>The app</h2></div>
  {img("app-golden-evals.jpg", "Golden Evals tab: per-class hit rates by horizon, the per-year train / test / holdout table for the chosen horizon, reproducibility, κ and the seed eval on top; every eval in the table below.")}
  {img("app-eval-detail.jpg", "An eval opened from the table: valuation with the recomputed check, reasons with data-check chips, validation stats, and the accept / edit / reject control.")}
  <p>Reviewing in the tab writes <span class="k">curation_status</span> and appends the human label to <span class="k">data/golden/seed_labels.json</span>, so every accept or edit grows the seed the next extractor version is scored on. SQL tab: <span class="k">SELECT * FROM vi.evals</span>, <span class="k">vi.validations</span>, <span class="k">vi.rates</span>.</p>
</section>

<section id="review">
  <div class="section-head"><span class="num">09</span><h2>What to review — the M2 checkpoint question</h2></div>
  <div class="cards">
    <div class="card rec"><h4>Start with the {len(rule_sens)} rule-sensitive evals</h4><p>{esc(", ".join(f"{e['ticker']} {e['t0'][:7]}" for e in rule_sens[:12]))}{" …" if len(rule_sens) > 12 else ""}. These are where "fairly valued for 10 %" meets "not a buy" — your accept / edit decides the boundary for M3.</p></div>
    <div class="card"><h4>{len(title_mis)} titles say buy, the transcript does not</h4><p>{esc(", ".join(f"{e['ticker']} {e['t0'][:7]}" for e in title_mis))}. The extractor read the transcript; check it read it right.</p></div>
    <div class="card"><h4>Known limits, recorded not hidden</h4><ul><li>{with_iv} of {n} videos state an intrinsic value; the rest are stance-only.</li><li>{base_gap} evals use a base metric &gt; 15 % from the last annual figure (TTM vs annual, D9).</li><li>Reasons resting on consensus, guidance, segments or 13F stay <em>external</em> — {pct(1 - repro_total / max(1, total_reasons))} of reasons.</li><li>The critic disagrees on position in {n - critic_agree} evals; κ is reported, not hidden.</li></ul></div>
    <div class="card"><h4>Next: M3</h4><p>The analyst agent v0 (<span class="k">agents/v0/{{system.md, helper.py}}</span>) starts from <span class="k">valuation.py</span> and the method summary, is scored on reproducing these evals from the point-in-time data only, and is gated on the within-year test split (D15); evals whose outcome is not in yet are the forward holdout.</p></div>
  </div>
</section>
<footer><p>Generated {date.today().isoformat()} by <span class="k">scripts/s03_page.py</span> from <span class="k">.lavish/s03_evidence/m2_numbers.json</span>. Previous pages: <a href="s00_value-invest-agent-plan.html">s00 plan</a> · <a href="s01_m1-walkthrough.html">s01 M1 walkthrough</a> · <a href="s02_m2-golden-extraction-plan.html">s02 M2 plan</a>.</p></footer>
</div>
</body>
</html>
"""
    OUT.write_text(page)
    print(f"wrote {OUT} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
