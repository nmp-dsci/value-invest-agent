"""Every number the M2 walkthrough page quotes, from the live DuckDB + checkpoint files → JSON.

Usage: uv run python scripts/m2_numbers.py > .lavish/s03_evidence/m2_numbers.json
Read-only; run with `vi serve` and pipeline commands stopped."""

from __future__ import annotations

import json
import sys

from value_invest import db
from value_invest.config import ROOT, settings
from value_invest.golden.validate import validation_summary


def rows(con, sql, params=None):
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def main() -> None:
    con = db.connect(read_only=True)
    s = settings()
    out: dict = {"since": str(s.since), "until": str(s.until), "per_year": s.sample_per_year}
    out["tables"] = db.table_counts(con)
    last = con.execute("SELECT max(date) FROM vi.prices").fetchone()
    out["last_price_date"] = str(last[0]) if last else None
    out["funnel"] = rows(
        con,
        """SELECT year_bucket, count(*) videos, count(*) FILTER (WHERE kind='single') single,
        count(*) FILTER (WHERE in_sample) sampled, count(*) FILTER (WHERE in_sample AND transcript_status='indexed') indexed
        FROM vi.videos WHERE year_bucket IS NOT NULL GROUP BY 1 ORDER BY 1""",
    )
    out["evals"] = rows(
        con,
        """SELECT e.video_id, e.ticker, e.t0, v.title, v.year_bucket, e.position, e.stance_detail, e.personal_action,
        e.expected_return_pct, e.iv_weighted_stated, e.price_at_t0, e.rule_sensitive, e.title_says_buy, e.split, e.curation_status,
        e.extractor_version, json_extract_string(e.critic,'$.own_stance_detail') critic_stance,
        CAST(json_extract(e.critic,'$.position_agrees') AS BOOLEAN) critic_agrees,
        CAST(json_extract(e.checks,'$.reproducible_share') AS DOUBLE) reproducible_share,
        CAST(json_extract(e.checks,'$.faithful_share') AS DOUBLE) faithful_share,
        json_extract_string(e.checks,'$.price_check') price_check,
        CAST(json_extract(e.checks,'$.iv_ok') AS INTEGER) iv_ok, CAST(json_extract(e.checks,'$.iv_compared') AS INTEGER) iv_compared,
        CAST(json_extract(e.checks,'$.base_metric_gap_pct') AS DOUBLE) base_gap, e.headline_quote,
        (SELECT json_group_object(horizon_m, json_object('excess', excess, 'verdict', verdict)) FROM vi.validations x WHERE x.video_id=e.video_id) validations
        FROM vi.evals e JOIN vi.videos v USING (video_id) ORDER BY e.t0""",
    )
    for e in out["evals"]:
        e["validations"] = json.loads(e["validations"]) if e["validations"] else {}
    out["reasons"] = rows(
        con,
        """SELECT r.category, r.direction, r.reproducible, count(*) n FROM (
        SELECT json_extract_string(x,'$.category') category, json_extract_string(x,'$.direction') direction,
               json_extract_string(x,'$.data_check.reproducible') reproducible
        FROM (SELECT unnest(from_json(reasons,'["JSON"]')) x FROM vi.evals)) r GROUP BY 1,2,3 ORDER BY 4 DESC""",
    )
    out["validation"] = validation_summary(con)
    out["mix"] = rows(
        con,
        """SELECT v.year_bucket, e.split, count(*) n, count(*) FILTER (WHERE position='BUY') buy,
        count(*) FILTER (WHERE position='HOLD') AS "hold", count(*) FILTER (WHERE position='SELL') sell, count(*) FILTER (WHERE rule_sensitive) rule_sensitive
        FROM vi.evals e JOIN vi.videos v USING (video_id) GROUP BY 1,2 ORDER BY 1""",
    )
    out["tickers"] = rows(
        con,
        "SELECT count(*) FILTER (WHERE edgar_filer) filers, count(*) FILTER (WHERE edgar_filer=FALSE) non_filers, count(*) FILTER (WHERE edgar_filer IS NULL) unchecked FROM vi.tickers",
    )
    for name in (
        "seed_eval_v0",
        "seed_eval_v1",
        "seed_eval_v2",
        "kappa",
        "method_summary",
        "stated_ivs",
    ):
        p = ROOT / "data" / "golden" / f"{name}.json"
        if p.exists():
            d = json.loads(p.read_text())
            d.pop("rows", None)
            out[name] = d
    json.dump(out, sys.stdout, indent=1, default=str)


if __name__ == "__main__":
    main()
