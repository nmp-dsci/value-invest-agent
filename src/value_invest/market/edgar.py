"""SEC EDGAR ``companyfacts`` → annual statements with real filing dates.

Why: yfinance returns four complete fiscal years. EDGAR's XBRL API is free,
goes back to ~2009 for every US filer, and every value carries ``filed`` —
the date the market first saw it — so the as-of rule becomes exact for these
names instead of "period end + 90 days". Non-US names (no SEC filings) keep
the yfinance rows.

Rules the SEC sets: declare who you are in the User-Agent (``SEC_USER_AGENT``,
"Name email"), stay under ~10 requests/s. Responses are cached under
``.vi/edgar/``.

Value selection per (concept, fiscal year): among entries from annual forms
(10-K, 20-F, 40-F) with ``fp == FY`` whose period is a full year, take the
**earliest filing** — the original report, not a later restatement — so
``filed_at`` is when the number first became public."""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from value_invest.config import settings

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
ANNUAL_FORMS = ("10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F")

# (kind, our line item) ← us-gaap concepts in priority order. Names match
# yfinance's so the app and the coverage view treat both sources alike.
CONCEPTS: dict[tuple[str, str], list[str]] = {
    ("income", "Total Revenue"): [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenuesNetOfInterestExpense",
    ],
    ("income", "Gross Profit"): ["GrossProfit"],
    ("income", "Operating Income"): ["OperatingIncomeLoss"],
    ("income", "Net Income"): ["NetIncomeLoss", "ProfitLoss"],
    ("income", "Diluted EPS"): ["EarningsPerShareDiluted"],
    ("income", "Interest Expense"): ["InterestExpense", "InterestExpenseNonoperating"],
    ("income", "Income Tax Expense"): ["IncomeTaxExpenseBenefit"],
    ("balance", "Total Assets"): ["Assets"],
    ("balance", "Total Liabilities"): ["Liabilities"],
    ("balance", "Stockholders Equity"): [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    ("balance", "Cash And Cash Equivalents"): [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    ("balance", "Current Assets"): ["AssetsCurrent"],
    ("balance", "Current Liabilities"): ["LiabilitiesCurrent"],
    ("balance", "Long Term Debt"): ["LongTermDebtNoncurrent", "LongTermDebt"],
    ("balance", "Current Debt"): ["DebtCurrent", "LongTermDebtCurrent"],
    ("balance", "Shares Outstanding"): ["CommonStockSharesOutstanding"],
    ("cashflow", "Operating Cash Flow"): ["NetCashProvidedByUsedInOperatingActivities"],
    ("cashflow", "Capital Expenditure"): [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    ("cashflow", "Cash Dividends Paid"): ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    ("cashflow", "Repurchase Of Capital Stock"): ["PaymentsForRepurchaseOfCommonStock"],
    ("cashflow", "Depreciation And Amortization"): [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
    ],
}
# yfinance reports these outflows as negatives; EDGAR reports payments as positives.
NEGATE = {"Capital Expenditure", "Cash Dividends Paid", "Repurchase Of Capital Stock"}
DERIVED = {  # computed after the concept rows, yfinance-style
    ("cashflow", "Free Cash Flow"): lambda r: (
        r.get(("cashflow", "Operating Cash Flow")) is not None
        and r.get(("cashflow", "Capital Expenditure")) is not None
        and r[("cashflow", "Operating Cash Flow")] + r[("cashflow", "Capital Expenditure")]
    ),
    ("balance", "Total Debt"): lambda r: (
        r.get(("balance", "Long Term Debt")) is not None
        and r[("balance", "Long Term Debt")] + (r.get(("balance", "Current Debt")) or 0.0)
    ),
    ("balance", "Working Capital"): lambda r: (
        r.get(("balance", "Current Assets")) is not None
        and r.get(("balance", "Current Liabilities")) is not None
        and r[("balance", "Current Assets")] - r[("balance", "Current Liabilities")]
    ),
}


class EdgarError(RuntimeError):
    pass


class Edgar:
    def __init__(
        self,
        user_agent: str | None = None,
        cache_dir: Path | None = None,
        min_interval_s: float = 0.15,
    ) -> None:
        self.user_agent = user_agent or settings().sec_user_agent
        if not self.user_agent or "@" not in self.user_agent:
            raise EdgarError(
                "SEC_USER_AGENT must be set to 'Name email@domain' (SEC fair-access policy)"
            )
        self.cache_dir = cache_dir or settings().cache_dir / "edgar"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval_s = min_interval_s
        self._last = 0.0
        self.calls = 0

    def _get(self, url: str, cache_name: str, max_age_days: int = 7) -> Any:
        cache = self.cache_dir / cache_name
        if cache.exists() and (time.time() - cache.stat().st_mtime) < max_age_days * 86400:
            return json.loads(cache.read_text())
        wait = self.min_interval_s - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        r = httpx.get(
            url,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=60,
            follow_redirects=True,
        )
        self._last = time.time()
        self.calls += 1
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise EdgarError(f"HTTP {r.status_code} for {url}: {r.text[:120]}")
        data = r.json()
        cache.write_text(json.dumps(data))
        return data

    def cik_map(self) -> dict[str, int]:
        data = self._get(TICKERS_URL, "company_tickers.json", max_age_days=30)
        return {str(v["ticker"]).upper(): int(v["cik_str"]) for v in data.values()}

    def cik_for(self, ticker: str) -> int | None:
        m = self.cik_map()
        t = ticker.upper()
        return m.get(t) or m.get(
            t.replace("-", ".")
        )  # BRK-B is BRK-B on SEC's list; keep both forms

    def companyfacts(self, cik: int) -> dict[str, Any] | None:
        return self._get(FACTS_URL.format(cik=cik), f"companyfacts_{cik:010d}.json")


def _full_year(e: dict[str, Any]) -> bool:
    if "start" not in e:  # instant concept (balance sheet)
        return True
    try:
        days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
    except ValueError:
        return False
    return 340 <= days <= 380


def annual_statements(ticker: str, facts: dict[str, Any], since_year: int = 2010) -> pd.DataFrame:
    """Long frame in vi.statements shape from one companyfacts document."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    rows: list[dict[str, Any]] = []
    by_fy: dict[date, dict[tuple[str, str], float]] = {}
    filed_by_fy: dict[date, date] = {}
    for (kind, item), concepts in CONCEPTS.items():
        for concept in concepts:
            units = (gaap.get(concept) or {}).get("units") or {}
            entries = units.get("USD") or units.get("USD/shares") or units.get("shares") or []
            picked: dict[date, dict[str, Any]] = {}
            for e in entries:
                if e.get("fp") != "FY" or e.get("form") not in ANNUAL_FORMS or not _full_year(e):
                    continue
                end = date.fromisoformat(e["end"])
                if end.year < since_year:
                    continue
                # earliest filing wins: the original report, not a restatement
                if end not in picked or e["filed"] < picked[end]["filed"]:
                    picked[end] = e
            if picked:
                for end, e in picked.items():
                    val = float(e["val"])
                    if item in NEGATE:
                        val = -abs(val)
                    filed = date.fromisoformat(e["filed"])
                    by_fy.setdefault(end, {})[(kind, item)] = val
                    filed_by_fy[end] = min(filed, filed_by_fy.get(end, filed))
                break  # first concept with data wins for this line item
    for end, items in by_fy.items():
        for key, fn in DERIVED.items():
            v = fn(items)
            if v is not False and v is not None:
                items[key] = float(v)
        filed = filed_by_fy[end]
        for (kind, item), val in items.items():
            rows.append(
                {
                    "ticker": ticker,
                    "period_end": end,
                    "kind": kind,
                    "freq": "annual",
                    "line_item": item,
                    "value": val,
                    "filed_at": filed,
                    "available_from": filed,
                    "source": "edgar",
                }
            )
    return pd.DataFrame(
        rows,
        columns=[
            "ticker",
            "period_end",
            "kind",
            "freq",
            "line_item",
            "value",
            "filed_at",
            "available_from",
            "source",
        ],
    )


def fetch_edgar_statements(ticker: str, client: Edgar | None = None) -> pd.DataFrame | None:
    """None when the ticker is not an SEC filer with us-gaap facts."""
    client = client or Edgar()
    cik = client.cik_for(ticker)
    if cik is None:
        return None
    facts = client.companyfacts(cik)
    if not facts or not ((facts.get("facts") or {}).get("us-gaap")):
        return None
    df = annual_statements(ticker, facts)
    path = settings().cache_dir / "market" / ticker.replace("/", "_") / "statements_edgar.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


def _iso(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()
