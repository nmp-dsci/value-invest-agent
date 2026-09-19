"""Settings and paths. Boots keyless: nothing here requires a token or key.

Secrets are read from ``./.env`` then ``~/.env`` with ``dotenv_values`` and kept
on the settings object — they are deliberately *not* exported into
``os.environ``, because ``~/.env`` in this workspace also carries an
``ANTHROPIC_API_KEY`` and exporting it would trip the subscription billing
guard in ``llm.py`` (and, worse, make the Agent SDK bill per token).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def _env() -> dict[str, str]:
    merged: dict[str, str] = {}
    for path in (Path.home() / ".env", ROOT / ".env"):  # project file wins
        if path.exists():
            merged.update({k: v for k, v in dotenv_values(path).items() if v is not None})
    merged.update({k: v for k, v in os.environ.items() if k.startswith(("VI_", "BILLING"))})
    return merged


@dataclass(frozen=True)
class Settings:
    supadata_api_key: str
    billing: str = "subscription"
    demo_mode: bool = False
    model: str = "claude-sonnet-5"
    channel: str = "@Value-Investing"
    channel_id: str = "UCrTTBSUr0zhPU56UQljag5A"
    since: date = date(2022, 9, 17)
    until: date = date(2026, 9, 17)
    sample_per_year: int = 10
    sample_seed: int = 42
    duckdb_path: Path = ROOT / "data" / "value_invest.duckdb"
    cache_dir: Path = ROOT / ".vi"
    transcript_lab_root: Path = ROOT.parent / "transcript-rag-agent"
    transcript_lab_chroma: Path = ROOT.parent / "transcript-rag-agent" / ".yt-agent" / "chroma"
    transcript_lab_api: str = "http://127.0.0.1:8000"
    horizons_months: tuple[int, ...] = (6, 12, 24)
    default_benchmark: str = "SPY"
    prices_from: date = date(2017, 1, 1)  # 5 years before the earliest sampled T0 (2022-09)
    # Annual-only as-of rule: a fiscal year's statements become visible this
    # many days after period end unless a real filing date is known.
    annual_lag_days: int = 90
    extra: dict[str, str] = field(default_factory=dict)


@lru_cache(maxsize=1)
def settings() -> Settings:
    e = _env()

    def d(key: str, default: date) -> date:
        return date.fromisoformat(e[key]) if e.get(key) else default

    return Settings(
        supadata_api_key=e.get("SUPADATA_API_KEY") or e.get("SUPERDATA_API_KEY") or "",
        billing=e.get("BILLING", "subscription"),
        demo_mode=e.get("VI_DEMO_MODE", e.get("DEMO_MODE", "0")) in {"1", "true", "True"},
        model=e.get("VI_MODEL", "claude-sonnet-5"),
        channel=e.get("VI_CHANNEL", "@Value-Investing"),
        channel_id=e.get("VI_CHANNEL_ID", "UCrTTBSUr0zhPU56UQljag5A"),
        since=d("VI_SINCE", date(2022, 9, 17)),
        until=d("VI_UNTIL", date(2026, 9, 17)),
        sample_per_year=int(e.get("VI_SAMPLE_PER_YEAR", "10")),
        sample_seed=int(e.get("VI_SAMPLE_SEED", "42")),
        duckdb_path=Path(e.get("VI_DUCKDB_PATH", str(ROOT / "data" / "value_invest.duckdb"))),
        cache_dir=Path(e.get("VI_CACHE_DIR", str(ROOT / ".vi"))),
        transcript_lab_root=Path(
            e.get("TRANSCRIPT_LAB_ROOT", str(ROOT.parent / "transcript-rag-agent"))
        ),
        transcript_lab_chroma=Path(
            e.get(
                "TRANSCRIPT_LAB_CHROMA_PATH",
                str(ROOT.parent / "transcript-rag-agent" / ".yt-agent" / "chroma"),
            )
        ),
        transcript_lab_api=e.get("TRANSCRIPT_LAB_API", "http://127.0.0.1:8000"),
        default_benchmark=e.get("VI_DEFAULT_BENCHMARK", "SPY"),
    )
