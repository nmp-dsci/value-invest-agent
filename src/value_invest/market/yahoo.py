"""yfinance loaders → parquet cache under .vi/market/<ticker>/.

Prices: daily OHLCV + adjusted close from VI prices_from (2018). Statements:
**annual** income / balance / cash-flow only (the M1 decision); yfinance returns
≈ 4–5 fiscal years. Each fiscal year becomes visible to the as-of view at
``period_end + annual_lag_days`` unless a real filing date is known (EDGAR,
deferred)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from value_invest.config import settings

KINDS = {"income": "income_stmt", "balance": "balance_sheet", "cashflow": "cashflow"}

# Benchmark by Yahoo suffix; SPY for US listings and anything unmapped.
BENCHMARKS = {
    ".PA": "^STOXX50E", ".DE": "^STOXX50E", ".AS": "^STOXX50E", ".MI": "^STOXX50E", ".MC": "^STOXX50E",
    ".HE": "^STOXX50E", ".SW": "^STOXX50E", ".L": "^FTSE", ".HK": "^HSI", ".T": "^N225",
    ".TO": "^GSPTSE", ".AX": "^AXJO", ".KS": "^KS11", ".SS": "000001.SS", ".SZ": "399001.SZ",
}


def benchmark_for(ticker: str) -> str:
    for suffix, bench in BENCHMARKS.items():
        if ticker.upper().endswith(suffix):
            return bench
    return settings().default_benchmark


def _dir(ticker: str) -> Path:
    d = settings().cache_dir / "market" / ticker.replace("/", "_")
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_prices(ticker: str, refresh: bool = False) -> pd.DataFrame:
    """Long frame: ticker, date, open, high, low, close, adj_close, volume."""
    path = _dir(ticker) / "prices.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    import yfinance as yf

    h = yf.Ticker(ticker).history(start=str(settings().prices_from), auto_adjust=False)
    if h is None or h.empty:
        df = pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"])
    else:
        df = h.reset_index().rename(
            columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close", "Volume": "volume"}
        )
        df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.date
        df.insert(0, "ticker", ticker)
        df = df[["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]]
    df.to_parquet(path, index=False)
    return df


def fetch_statements(ticker: str, refresh: bool = False) -> pd.DataFrame:
    """Long frame: ticker, period_end, kind, freq, line_item, value, filed_at, available_from, source."""
    path = _dir(ticker) / "statements_annual.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    import yfinance as yf

    tk = yf.Ticker(ticker)
    lag = timedelta(days=settings().annual_lag_days)
    frames = []
    for kind, attr in KINDS.items():
        wide = getattr(tk, attr)
        if wide is None or wide.empty:
            continue
        # Plain loop instead of DataFrame.melt: yfinance frames carry a
        # DatetimeIndex on the columns and occasionally duplicate line-item
        # names, both of which trip pandas' melt/concat path.
        records = []
        for col in wide.columns:
            pe = pd.Timestamp(col).date()
            series = wide[col]
            for li, val in zip(wide.index, series.values):
                if val is None or pd.isna(val):
                    continue
                records.append({"line_item": str(li), "period_end": pe, "value": float(val), "kind": kind})
        if records:
            frames.append(pd.DataFrame(records))
    if frames:
        df = pd.concat(frames, ignore_index=True)
        df.insert(0, "ticker", ticker)
        df["freq"] = "annual"
        df["filed_at"] = None
        df["available_from"] = [pe + lag for pe in df["period_end"]]
        df["source"] = "yfinance"
        df = df[["ticker", "period_end", "kind", "freq", "line_item", "value", "filed_at", "available_from", "source"]]
        df["value"] = df["value"].astype(float)
    else:
        df = pd.DataFrame(columns=["ticker", "period_end", "kind", "freq", "line_item", "value", "filed_at", "available_from", "source"])
    df.to_parquet(path, index=False)
    return df


def fetch_info(ticker: str) -> dict[str, Any]:
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    return {"name": info.get("longName") or info.get("shortName"), "exchange": info.get("exchange"), "currency": info.get("currency")}


def first_last(df: pd.DataFrame) -> tuple[date | None, date | None]:
    if df.empty:
        return None, None
    return min(df["date"]), max(df["date"])
