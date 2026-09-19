"""`vi` — the pipeline as subcommands. Each stage writes an idempotent table."""

from __future__ import annotations

import json

import typer
from rich import print as rprint

from value_invest import db
from value_invest.config import settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="value·invest agent pipeline")
db_app = typer.Typer(help="DuckDB schema and counts")
app.add_typer(db_app, name="db")


@db_app.command("init")
def db_init() -> None:
    con = db.connect()
    rprint({"path": str(settings().duckdb_path), "tables": db.table_counts(con)})


@db_app.command("counts")
def db_counts() -> None:
    rprint(db.table_counts(db.connect()))


@app.command()
def catalog(refresh_listing: bool = False) -> None:
    """S1a: every channel video with a date (exact where cached, else approximate) → vi.videos."""
    from value_invest.catalog.build import build_catalog

    con = db.connect()
    rprint(build_catalog(con, refresh_listing=refresh_listing))


@app.command("refine-dates")
def refine_dates(scope: str = "singles", limit: int | None = None, pace: float = 1.2) -> None:
    """S1a′: exact dates (per-video yt-dlp) for single-stock candidates near the window, or the sample."""
    from value_invest.catalog.build import refine_dates as _refine

    con = db.connect()
    rprint(_refine(con, scope=scope, limit=limit, pace_s=pace))


@app.command()
def classify(
    batch: int = 40,
    limit: int | None = None,
    only_missing: bool = True,
    eval_seed: bool = False,
    workers: int = 3,
) -> None:
    """S1b: title (+description) → kind + tickers via the Agent SDK → vi.title_labels."""
    from value_invest.classify.run import classify_catalog, evaluate_seed

    if eval_seed:
        rprint(evaluate_seed())
        return
    con = db.connect()
    rprint(
        classify_catalog(con, batch=batch, limit=limit, only_missing=only_missing, workers=workers)
    )


@app.command()
def sample(
    per_year: int | None = None, seed: int | None = None, edgar_only: bool | None = None
) -> None:
    """S1c: pick N single-stock videos per window year, seeded → vi.videos.in_sample (US 10-K filers by default)."""
    from value_invest.sample import draw_sample

    con = db.connect()
    rprint(draw_sample(con, per_year=per_year, seed=seed, edgar_only=edgar_only))


@app.command()
def ingest(concurrency: int = 1, refresh: bool = False) -> None:
    """S1d: index every sampled video in transcript·lab (index-rag) and record status."""
    from value_invest.ingest.run import ingest_sample

    con = db.connect()
    rprint(ingest_sample(con, concurrency=concurrency, refresh=refresh))


@app.command()
def market(only_missing: bool = True) -> None:
    """S2: Yahoo daily prices + annual statements for every sampled ticker → vi.prices / vi.statements."""
    from value_invest.market.load import load_market

    con = db.connect()
    rprint(load_market(con, only_missing=only_missing))


@app.command()
def edgar(check_candidates: bool = False, recheck: bool = False) -> None:
    """S2b: 10+ years of annual statements with filing dates for SEC filers (EDGAR) → vi.statements.
    --check-candidates instead marks every single-stock candidate ticker as a filer with annual
    us-gaap statements or not; --recheck also revisits tickers marked False."""
    from value_invest.market.load import check_edgar_candidates, load_edgar

    con = db.connect()
    rprint(check_edgar_candidates(con, recheck=recheck) if check_candidates else load_edgar(con))


@app.command()
def coverage() -> None:
    """S2: per-video coverage — prices at T0, annual reports visible at T0."""
    from value_invest.market.coverage import coverage_table

    con = db.connect(read_only=True)
    rows = coverage_table(con)
    rprint(json.dumps(rows, indent=1, default=str)[:4000])


@app.command()
def extract(
    version: str = "v0",
    only: list[str] | None = None,
    force: bool = False,
    workers: int = 3,
    no_critic: bool = False,
) -> None:
    """S4: transcript → GoldenEval (extract · ground · critic · checkpoint) → vi.evals. Cache-aware."""
    from value_invest.golden.checkpoint import process_all

    con = db.connect()
    rprint(
        process_all(
            con, version, only=only or None, force=force, workers=workers, critic=not no_critic
        )
    )


golden_app = typer.Typer(help="Golden-eval checkpoint: seed eval, κ, method summary (S4.3)")
app.add_typer(golden_app, name="golden")


@golden_app.command("eval-seed")
def golden_eval_seed(version: str = "v0") -> None:
    """Score vi.evals against data/golden/seed_labels.json → seed_eval_<version>.json."""
    from value_invest.golden.checkpoint import seed_eval

    rprint(seed_eval(db.connect(read_only=True), version))


@golden_app.command("kappa")
def golden_kappa() -> None:
    """Inter-extractor κ (extractor vs critic) on stance_detail → kappa.json."""
    from value_invest.golden.checkpoint import kappa

    rprint(kappa(db.connect(read_only=True)))


@golden_app.command("summary")
def golden_summary() -> None:
    """The distilled method: discount rates, multiples, probabilities, reason mix → method_summary.json."""
    from value_invest.golden.checkpoint import method_summary

    rprint(method_summary(db.connect(read_only=True)))


@app.command()
def validate() -> None:
    """S5: forward returns vs the benchmark at T0 + 6 / 12 / 24 m and the verdict on every eval → vi.validations."""
    from value_invest.golden.validate import validate_all

    con = db.connect()
    rprint(validate_all(con))


@app.command()
def rates() -> None:
    """FRED DGS10 / DGS3MO daily yields → vi.rates (the risk-free he compares dividend yields with)."""
    from value_invest.market.fred import load_rates

    con = db.connect()
    rprint(load_rates(con))


valuation_app = typer.Typer(help="The author's intrinsic-value template (S4.0)")
app.add_typer(valuation_app, name="valuation")


@valuation_app.command("check")
def valuation_check() -> None:
    """S4.0: recompute every intrinsic value he states on camera and show the error."""
    from value_invest.valuation import fidelity

    rows = fidelity()
    for r in rows:
        flag = "ok " if r["ok"] else "OUT"
        rprint(
            f"{flag} {r['ticker']:6} {r['t0']} {r['scenario']:7} stated {r['stated']:>8} "
            f"model {r['model']:>8}  {r['error'] * 100:+.1f}% (±{r['tolerance'] * 100:.0f}%)"
        )
    rprint({"cases": len(rows), "within_tolerance": sum(r["ok"] for r in rows)})


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8791, reload: bool = False) -> None:
    """S3: the walkthrough app (FastAPI + built React bundle)."""
    import uvicorn

    uvicorn.run(
        "value_invest.serving.app:create_app", factory=True, host=host, port=port, reload=reload
    )


if __name__ == "__main__":
    app()
