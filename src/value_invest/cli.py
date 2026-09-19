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
def sample(per_year: int | None = None, seed: int | None = None) -> None:
    """S1c: pick N single-stock videos per window year, seeded → vi.videos.in_sample."""
    from value_invest.sample import draw_sample

    con = db.connect()
    rprint(draw_sample(con, per_year=per_year, seed=seed))


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
def edgar() -> None:
    """S2b: 10+ years of annual statements with filing dates for US filers (SEC EDGAR) → vi.statements."""
    from value_invest.market.load import load_edgar

    con = db.connect()
    rprint(load_edgar(con))


@app.command()
def coverage() -> None:
    """S2: per-video coverage — prices at T0, annual reports visible at T0."""
    from value_invest.market.coverage import coverage_table

    con = db.connect(read_only=True)
    rows = coverage_table(con)
    rprint(json.dumps(rows, indent=1, default=str)[:4000])


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8791, reload: bool = False) -> None:
    """S3: the walkthrough app (FastAPI + built React bundle)."""
    import uvicorn

    uvicorn.run(
        "value_invest.serving.app:create_app", factory=True, host=host, port=port, reload=reload
    )


if __name__ == "__main__":
    app()
