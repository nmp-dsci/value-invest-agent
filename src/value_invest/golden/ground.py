"""Stage 3 — ground every reason in the point-in-time data. No model call.

For each reason the extractor returned, the numbers he cited are resolved to
line items visible at T0 (``vi.statements_as_of``), prices ≤ T0 and the FRED
rates, and compared with what he said. The valuation inputs are re-run through
``valuation.py`` and compared with the intrinsic values he read off his sheet.
The result says, per reason, whether an agent with only our data could have
made the argument — the number the M2 review turns on."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import duckdb

from value_invest import valuation as val
from value_invest.golden.models import DataCheck, GoldenEvalDraft, Reason, Reproducible

PRICE_WINDOW_DAYS = 7  # ≈ 5 trading days either side of T0
PRICE_TOL = 0.10
METRIC_REL_TOL = 0.15  # his rounding: "110 billion" for 94.9, "P/E 40" for 36.6
IV_TOL = 0.10

# yfinance / EDGAR line items we read, by our metric key
LINE = {
    "eps": ("income", ["Diluted EPS", "Basic EPS"]),
    "revenue": ("income", ["Total Revenue", "Operating Revenue"]),
    "gross_profit": ("income", ["Gross Profit"]),
    "operating_income": ("income", ["Operating Income"]),
    "net_income": ("income", ["Net Income", "Net Income Common Stockholders"]),
    "interest_expense": ("income", ["Interest Expense", "Interest Expense Non Operating"]),
    "total_assets": ("balance", ["Total Assets"]),
    "total_debt": ("balance", ["Total Debt", "Long Term Debt And Capital Lease Obligation"]),
    "cash": (
        "balance",
        ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
    ),
    "equity": ("balance", ["Stockholders Equity", "Common Stock Equity"]),
    "shares": (
        "balance",
        [
            "Shares Outstanding",
            "Ordinary Shares Number",
            "Diluted Average Shares",
            "Basic Average Shares",
        ],
    ),
    "ocf": ("cashflow", ["Operating Cash Flow"]),
    "capex": ("cashflow", ["Capital Expenditure"]),
    "fcf": ("cashflow", ["Free Cash Flow"]),
    "dividends_paid": ("cashflow", ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
    "repurchase": ("cashflow", ["Repurchase Of Capital Stock", "Common Stock Payments"]),
}
MONEY = {
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "interest_expense",
    "total_assets",
    "total_debt",
    "cash",
    "equity",
    "ocf",
    "capex",
    "fcf",
    "dividends_paid",
    "repurchase",
    "market_cap",
    "net_debt",
}
PCT = {
    "buyback_yield",
    "dividend_yield",
    "fcf_yield",
    "earnings_yield",
    "payout_ratio",
    "net_margin",
    "operating_margin",
    "gross_margin",
    "roe",
    "revenue_growth_1y",
    "revenue_growth_3y",
    "eps_growth_1y",
    "ni_growth_3y",
    "capex_to_revenue",
    "risk_free",
    "dividend_spread",
    "price_change_5y",
    "price_drawdown",
}
DERIVED_KEYS = PCT | {"pe", "dps", "market_cap", "net_debt", "debt_to_equity"}

# his words → our metric key; first match wins, so specific phrases come first
RULES: list[tuple[tuple[str, ...], str]] = [
    (("buyback yield", "repurchase yield"), "buyback_yield"),
    (("dividend yield",), "dividend_yield"),
    (("fcf yield", "free cash flow yield", "cash flow yield"), "fcf_yield"),
    (("earnings yield",), "earnings_yield"),
    (("payout",), "payout_ratio"),
    (
        (
            "p/e",
            "pe ratio",
            "p e ratio",
            "price to earnings",
            "price/earnings",
            "price-to-earnings",
            "earnings multiple",
            "pe multiple",
            "p ratio",
            "peer ratio",
            "terminal multiple",
            "multiple",
        ),
        "pe",
    ),
    (("eps", "earnings per share"), "eps"),
    (("dividend per share", "dps", "dividend"), "dps"),
    (("buyback", "repurchase", "share repurchase"), "repurchase"),
    (
        ("market cap", "market capitalization", "market capitalisation", "enterprise value"),
        "market_cap",
    ),
    (("free cash flow", "fcf"), "fcf"),
    (("operating cash flow", "cash from operations", "cash flow"), "ocf"),
    (("capex", "capital expenditure", "capital spending"), "capex"),
    (("net debt",), "net_debt"),
    (("debt", "borrowing", "leverage", "bonds"), "total_debt"),
    (("cash pile", "cash position", "cash"), "cash"),
    (("net margin", "profit margin", "net profit margin"), "net_margin"),
    (("operating margin", "ebit margin"), "operating_margin"),
    (("gross margin",), "gross_margin"),
    (("roe", "return on equity", "return on invested capital", "roic"), "roe"),
    (("revenue growth", "sales growth", "top line growth", "top-line growth"), "revenue_growth_1y"),
    (
        (
            "earnings growth",
            "eps growth",
            "profit growth",
            "income growth",
            "growth rate",
            "growth",
        ),
        "eps_growth_1y",
    ),
    (("revenue", "sales", "top line"), "revenue"),
    (("net income", "net profit", "earnings", "profit"), "net_income"),
    (("interest expense", "interest cost"), "interest_expense"),
    (
        (
            "treasury",
            "treasuries",
            "risk-free",
            "risk free",
            "10-year",
            "10 year",
            "bond yield",
            "interest rate",
            "fed rate",
        ),
        "risk_free",
    ),
    (("shares outstanding", "share count", "dilution", "shares"), "shares"),
    (
        ("drawdown", "from the high", "from its high", "from the peak", "off the peak"),
        "price_drawdown",
    ),
    (("5 year", "five year", "5-year", "last 5 years"), "price_change_5y"),
    (("stock price", "share price", "price", "stock"), "price"),
    (("total assets", "assets"), "total_assets"),
    (("equity", "book value"), "equity"),
]


# a number about a slice or a source we do not hold: segments, geographies,
# operating KPIs, guidance, consensus — these stay external whatever the noun
UNGROUNDABLE = (
    "china",
    "europe",
    "asia",
    "international",
    "us market",
    "u.s.",
    "region",
    "geograph",
    "segment",
    "share of",
    "market share",
    "cloud",
    "aws",
    "iphone",
    "services",
    "subscriber",
    "deliver",
    "unit",
    "store",
    "net flow",
    "outflow",
    "inflow",
    "aum",
    "assets under",
    "backlog",
    "commitment",
    "guidance",
    "target",
    "consensus",
    "analyst",
    "estimate",
    "expected",
    "wall street",
    "quarter",
    "last quarter",
    "q1",
    "q2",
    "q3",
    "q4",
    "13f",
    "stake",
    "position size",
    "life expectancy",
)


def resolve_metric_name(name: str) -> str | None:
    n = name.lower()
    if any(u in n for u in UNGROUNDABLE):
        return None
    for keys, metric in RULES:
        if any(k in n for k in keys):
            return metric
    return None


@dataclass
class AsOf:
    ticker: str
    t0: date
    price: float | None = None
    price_date: date | None = None
    closes_near_t0: list[float] = field(default_factory=list)
    fy_year: int | None = None
    fy_period_end: date | None = None
    fy_available_from: date | None = None
    latest: dict[str, float] = field(default_factory=dict)  # metric key → value (latest FY)
    history: dict[str, dict[int, float]] = field(default_factory=dict)  # metric key → {fy: value}
    risk_free: float | None = None
    metrics: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )  # key → {value, unit, origin, formula, line_items}


def _pick(items: dict[str, float], names: list[str]) -> tuple[float | None, str | None]:
    for n in names:
        if n in items and items[n] is not None:
            return float(items[n]), n
    return None, None


def load_as_of(con: duckdb.DuckDBPyConnection, ticker: str, t0: date) -> AsOf:
    a = AsOf(ticker=ticker, t0=t0)
    r = con.execute(
        "SELECT date, close FROM vi.prices WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT 1",
        [ticker, t0],
    ).fetchone()
    if r:
        a.price_date, a.price = r[0], float(r[1])
    a.closes_near_t0 = [
        float(x[0])
        for x in con.execute(
            "SELECT close FROM vi.prices WHERE ticker = ? AND date BETWEEN ? AND ?",
            [
                ticker,
                t0 - timedelta(days=PRICE_WINDOW_DAYS),
                t0 + timedelta(days=PRICE_WINDOW_DAYS),
            ],
        ).fetchall()
    ]
    rows = con.execute(
        "SELECT period_end, kind, line_item, value, available_from, source FROM vi.statements_as_of(?, ?) WHERE freq = 'annual'",
        [ticker, t0],
    ).fetchall()
    by_fy: dict[int, dict[str, float]] = {}
    src_fy: dict[int, dict[str, str]] = {}
    meta_fy: dict[int, tuple[date, date]] = {}
    for period_end, _kind, item, value, avail, source in rows:
        if value is None:
            continue
        fy = period_end.year
        d = by_fy.setdefault(fy, {})
        s = src_fy.setdefault(fy, {})
        if item not in d or (source == "edgar" and s.get(item) != "edgar"):
            d[item] = float(value)
            s[item] = source
        pe_, av = meta_fy.get(fy, (period_end, avail))
        meta_fy[fy] = (max(pe_, period_end), min(av, avail))
    complete = [fy for fy, d in by_fy.items() if "Total Revenue" in d or "Net Income" in d]
    for key, (_kind, names) in LINE.items():
        hist: dict[int, float] = {}
        for fy, d in by_fy.items():
            v, _ = _pick(d, names)
            if v is not None:
                hist[fy] = v
        if hist:
            a.history[key] = hist
    if complete:
        a.fy_year = max(complete)
        a.fy_period_end, a.fy_available_from = meta_fy[a.fy_year]
        for key, hist in a.history.items():
            if a.fy_year in hist:
                a.latest[key] = hist[a.fy_year]
            elif key == "shares" and hist:  # shares often sit on a different row set
                a.latest[key] = hist[max(hist)]
    try:
        rf = con.execute(
            "SELECT value FROM vi.rates WHERE series = 'DGS10' AND date <= ? ORDER BY date DESC LIMIT 1",
            [t0],
        ).fetchone()
        a.risk_free = float(rf[0]) if rf else None
    except duckdb.Error:
        a.risk_free = None
    a.metrics = _derive(a)
    return a


def _derive(a: AsOf) -> dict[str, dict[str, Any]]:
    m: dict[str, dict[str, Any]] = {}
    fy = f"FY{a.fy_year}" if a.fy_year else None

    def put(
        key: str, value: float | None, unit: str, origin: str, formula: str, items: list[str]
    ) -> None:
        if value is None:
            return
        m[key] = {
            "value": value,
            "unit": unit,
            "origin": origin,
            "formula": formula,
            "line_items": items,
            "period": fy if origin != "prices" else str(a.price_date),
        }

    if a.price is not None:
        put("price", a.price, "usd", "prices", "close ≤ T0", ["close"])
    L = a.latest
    for key in LINE:
        if key in L:
            unit = "per_share" if key == "eps" else "shares" if key == "shares" else "usd"
            put(key, L[key], unit, "statements", f"{LINE[key][1][0]} {fy}", [LINE[key][1][0]])
    if "dividends_paid" in L and "shares" in L and L["shares"]:
        put(
            "dps",
            abs(L["dividends_paid"]) / L["shares"],
            "per_share",
            "derived",
            "|Cash Dividends Paid| / shares",
            ["Cash Dividends Paid", "Shares Outstanding"],
        )
    if a.price and "shares" in L:
        put(
            "market_cap",
            a.price * L["shares"],
            "usd",
            "derived",
            "close × shares",
            ["close", "Shares Outstanding"],
        )
    if a.price and L.get("eps"):
        put(
            "pe",
            a.price / L["eps"],
            "ratio",
            "derived",
            "close / Diluted EPS",
            ["close", "Diluted EPS"],
        )
        put(
            "earnings_yield",
            L["eps"] / a.price,
            "pct",
            "derived",
            "Diluted EPS / close",
            ["close", "Diluted EPS"],
        )
    if "dps" in m and a.price:
        put(
            "dividend_yield",
            m["dps"]["value"] / a.price,
            "pct",
            "derived",
            "DPS / close",
            ["Cash Dividends Paid", "Shares Outstanding", "close"],
        )
        if a.risk_free is not None:
            put(
                "dividend_spread",
                m["dividend_yield"]["value"] - a.risk_free,
                "pct",
                "derived",
                "dividend yield − DGS10",
                ["Cash Dividends Paid", "close", "DGS10"],
            )
    if a.risk_free is not None:
        put("risk_free", a.risk_free, "pct", "rates", "FRED DGS10 ≤ T0", ["DGS10"])
    if "market_cap" in m:
        mc = m["market_cap"]["value"]
        if "repurchase" in L and mc:
            put(
                "buyback_yield",
                abs(L["repurchase"]) / mc,
                "pct",
                "derived",
                "|Repurchase| / market cap",
                ["Repurchase Of Capital Stock", "close", "Shares Outstanding"],
            )
        if "fcf" in L and mc:
            put(
                "fcf_yield",
                L["fcf"] / mc,
                "pct",
                "derived",
                "FCF / market cap",
                ["Free Cash Flow", "close", "Shares Outstanding"],
            )
    if L.get("revenue"):
        if "net_income" in L:
            put(
                "net_margin",
                L["net_income"] / L["revenue"],
                "pct",
                "derived",
                "Net Income / Revenue",
                ["Net Income", "Total Revenue"],
            )
        if "operating_income" in L:
            put(
                "operating_margin",
                L["operating_income"] / L["revenue"],
                "pct",
                "derived",
                "Operating Income / Revenue",
                ["Operating Income", "Total Revenue"],
            )
        if "gross_profit" in L:
            put(
                "gross_margin",
                L["gross_profit"] / L["revenue"],
                "pct",
                "derived",
                "Gross Profit / Revenue",
                ["Gross Profit", "Total Revenue"],
            )
        if "capex" in L:
            put(
                "capex_to_revenue",
                abs(L["capex"]) / L["revenue"],
                "pct",
                "derived",
                "|Capex| / Revenue",
                ["Capital Expenditure", "Total Revenue"],
            )
    if L.get("equity") and "net_income" in L:
        put(
            "roe",
            L["net_income"] / L["equity"],
            "pct",
            "derived",
            "Net Income / Equity",
            ["Net Income", "Stockholders Equity"],
        )
    if "total_debt" in L and "cash" in L:
        put(
            "net_debt",
            L["total_debt"] - L["cash"],
            "usd",
            "derived",
            "Total Debt − Cash",
            ["Total Debt", "Cash And Cash Equivalents"],
        )
    if "net_income" in L and L.get("dividends_paid") is not None and L["net_income"]:
        put(
            "payout_ratio",
            abs(L["dividends_paid"]) / L["net_income"],
            "pct",
            "derived",
            "|Dividends| / Net Income",
            ["Cash Dividends Paid", "Net Income"],
        )
    for key, out1, out3 in (
        ("revenue", "revenue_growth_1y", "revenue_growth_3y"),
        ("eps", "eps_growth_1y", None),
        ("net_income", None, "ni_growth_3y"),
    ):
        h = a.history.get(key, {})
        if a.fy_year and a.fy_year in h:
            if out1 and (a.fy_year - 1) in h and h[a.fy_year - 1]:
                put(
                    out1,
                    h[a.fy_year] / h[a.fy_year - 1] - 1,
                    "pct",
                    "derived",
                    f"{key} FY/FY−1 − 1",
                    [LINE[key][1][0]],
                )
            if out3 and (a.fy_year - 3) in h and h[a.fy_year - 3] > 0 and h[a.fy_year] > 0:
                put(
                    out3,
                    (h[a.fy_year] / h[a.fy_year - 3]) ** (1 / 3) - 1,
                    "pct",
                    "derived",
                    f"{key} 3-year CAGR",
                    [LINE[key][1][0]],
                )
    return m


def price_history_metrics(con: duckdb.DuckDBPyConnection, a: AsOf) -> None:
    """5-year change and drawdown from the 5-year high, from prices ≤ T0."""
    if a.price is None:
        return
    r = con.execute(
        "SELECT min(close), max(close), first(close ORDER BY date) FROM vi.prices WHERE ticker = ? AND date BETWEEN ? AND ?",
        [a.ticker, a.t0 - timedelta(days=5 * 365), a.t0],
    ).fetchone()
    if r and r[1]:
        a.metrics["price_drawdown"] = {
            "value": a.price / float(r[1]) - 1,
            "unit": "pct",
            "origin": "prices",
            "formula": "close / 5-year high − 1",
            "line_items": ["close"],
            "period": "5y",
        }
        if r[2]:
            a.metrics["price_change_5y"] = {
                "value": a.price / float(r[2]) - 1,
                "unit": "pct",
                "origin": "prices",
                "formula": "close / close 5 years ago − 1",
                "line_items": ["close"],
                "period": "5y",
            }


def _to_comparable(key: str, stated: float, unit: str | None) -> float:
    """His number in our unit: fractions for pct, dollars for money."""
    u = (unit or "").lower()
    if key in PCT:
        return (
            stated / 100.0 if (u in ("pct", "percent", "%", "") and abs(stated) > 1.0) else stated
        )
    if key in MONEY:
        if u in ("usd_bn", "bn", "billion", "billions", "b"):
            return stated * 1e9
        if u in ("usd_m", "m", "million", "millions", "mn"):
            return stated * 1e6
        if u in ("usd_tn", "tn", "trillion", "t"):
            return stated * 1e12
        if u in ("", "usd") and abs(stated) < 1e5:  # he speaks in billions
            return stated * 1e9 if abs(stated) < 1e4 else stated * 1e6
        return stated
    return stated


def _agrees(key: str, stated: float, as_of: float) -> bool:
    floor = 0.015 if key in PCT else 1.5 if key == "pe" else 0.5 if key in ("eps", "dps") else 0.0
    return abs(as_of - stated) <= max(METRIC_REL_TOL * abs(stated), floor)


def check_reason(reason: Reason, a: AsOf, iv_ok: bool | None) -> DataCheck:
    resolved: list[tuple[str, float | None, float, dict[str, Any]]] = []
    unresolved: list[str] = []
    for mm in reason.metrics:
        key = resolve_metric_name(mm.name)
        if key and key in a.metrics:
            info = a.metrics[key]
            stated = _to_comparable(key, mm.value, mm.unit) if mm.value is not None else None
            resolved.append((key, stated, float(info["value"]), info))
        else:
            unresolved.append(mm.name)
    if resolved:
        key, stated, as_of, info = resolved[0]
        for cand in resolved:  # prefer a mention with a number to compare
            if cand[1] is not None:
                key, stated, as_of, info = cand
                break
        origin = info["origin"]
        repro: Reproducible = (
            "derived"
            if origin in ("derived", "rates")
            else ("prices" if origin == "prices" else "statements")
        )
        agrees = _agrees(key, stated, as_of) if stated is not None else None
        gap = None
        if stated is not None and agrees is False:
            gap = f"he says {stated:g}, as-of {as_of:g} ({info.get('period')}); annual vs TTM or a different definition"
        if unresolved:
            gap = (gap + "; " if gap else "") + f"not in our data: {', '.join(unresolved[:3])}"
        return DataCheck(
            reproducible=repro,
            line_items=list(info["line_items"]),
            value_stated=stated,
            value_as_of=as_of,
            agrees=agrees,
            formula=info["formula"],
            as_of_period=str(info.get("period")),
            gap_note=gap,
        )
    if unresolved:
        return DataCheck(
            reproducible="external",
            line_items=[],
            gap_note=f"not in our data: {', '.join(unresolved[:4])}",
        )
    # no numbers cited: reproducibility follows the kind of argument
    c = reason.category
    if c == "valuation" and iv_ok is not None:
        return DataCheck(
            reproducible="derived",
            line_items=["Diluted EPS", "close"],
            agrees=iv_ok,
            formula="valuation.two_stage_iv on his inputs",
            gap_note=None,
        )
    if c in ("growth", "capital_allocation", "balance_sheet"):
        items = {
            "growth": ["Total Revenue", "Net Income"],
            "capital_allocation": ["Repurchase Of Capital Stock", "Cash Dividends Paid"],
            "balance_sheet": ["Total Debt", "Cash And Cash Equivalents"],
        }[c]
        have = any(
            k in a.latest
            for k in ("revenue", "net_income", "repurchase", "dividends_paid", "total_debt", "cash")
        )
        return DataCheck(
            reproducible="statements" if have else "external",
            line_items=items,
            gap_note="trajectory visible at T0; no number stated"
            if have
            else "no statements visible at T0",
        )
    if c == "macro_rates":
        return DataCheck(
            reproducible="derived" if a.risk_free is not None else "external",
            line_items=["DGS10"] if a.risk_free is not None else [],
            value_as_of=a.risk_free,
        )
    if c in ("sentiment", "management"):
        return DataCheck(reproducible="external", line_items=[])
    return DataCheck(reproducible="judgement", line_items=[])


def recompute_valuation(draft: GoldenEvalDraft, a: AsOf) -> dict[str, Any]:
    v = draft.valuation
    out: dict[str, Any] = {"scenarios": [], "within_band": None, "n_compared": 0, "n_ok": 0}
    if v.method == "none" or not v.base_metric or v.base_metric.value_stated is None:
        return out
    base = v.base_metric.value_stated
    r = v.discount_rate or val.DEFAULT_DISCOUNT
    payout = 1.0 if v.method == "dividend" else (v.payout_ratio or 0.0)
    if v.method == "eps_multiple" and v.payout_ratio is None and "payout_ratio" in a.metrics:
        payout = min(1.0, max(0.0, float(a.metrics["payout_ratio"]["value"])))
    weighted, ptot = 0.0, 0.0
    for s in v.scenarios:
        if s.g_y1_5 is None or s.terminal_multiple is None:
            out["scenarios"].append(
                {"name": s.name, "iv_model": None, "iv_stated": s.iv_stated, "ok": None}
            )
            continue
        g2 = s.g_y6_10 if s.g_y6_10 is not None else s.g_y1_5
        iv = val.two_stage_iv(base, s.g_y1_5, g2, s.terminal_multiple, r, payout)
        ok = None if s.iv_stated in (None, 0) else abs(iv / s.iv_stated - 1) <= IV_TOL
        if ok is not None:
            out["n_compared"] += 1
            out["n_ok"] += int(ok)
        if s.probability:
            weighted += s.probability * iv
            ptot += s.probability
        out["scenarios"].append(
            {
                "name": s.name,
                "iv_model": round(iv, 2),
                "iv_stated": s.iv_stated,
                "error": None if not s.iv_stated else round(iv / s.iv_stated - 1, 3),
                "ok": ok,
            }
        )
    if ptot > 0:
        out["iv_weighted_model"] = round(weighted / ptot, 2)
        if v.iv_weighted_stated:
            out["iv_weighted_ok"] = (
                abs(out["iv_weighted_model"] / v.iv_weighted_stated - 1) <= IV_TOL
            )
    normal = next(
        (
            s
            for s in v.scenarios
            if s.name == "normal" and s.g_y1_5 is not None and s.terminal_multiple is not None
        ),
        None,
    )
    if normal and a.price:
        g2 = normal.g_y6_10 if normal.g_y6_10 is not None else normal.g_y1_5
        try:
            out["expected_return_at_price"] = round(
                val.expected_return(
                    a.price, base, normal.g_y1_5, g2, normal.terminal_multiple, payout
                )
                * 100,
                1,
            )
        except Exception:  # noqa: BLE001 — a degenerate input just leaves the field empty
            pass
    # base metric: what he used vs the last annual figure visible at T0
    key = {
        "eps": "eps",
        "dps": "dps",
        "net_income": "net_income",
        "fcf_per_share": None,
        "other": None,
    }.get(v.base_metric.name)
    if key and key in a.metrics:
        as_of = float(a.metrics[key]["value"])
        if key == "net_income" and abs(base) < 1e4:
            as_of = as_of / 1e9  # he states net income in billions
        out["base_metric"] = {
            "name": v.base_metric.name,
            "stated": base,
            "as_of": round(as_of, 3),
            "period": a.metrics[key].get("period"),
            "gap_pct": round((base / as_of - 1) * 100, 1) if as_of else None,
        }
    out["within_band"] = (out["n_ok"] == out["n_compared"]) if out["n_compared"] else None
    return out


def ground(
    con: duckdb.DuckDBPyConnection, draft: GoldenEvalDraft, ticker: str, t0: date
) -> tuple[AsOf, dict[str, Any]]:
    a = load_as_of(con, ticker, t0)
    price_history_metrics(con, a)
    ivr = recompute_valuation(draft, a)
    iv_ok = ivr.get("within_band")
    for reason in draft.reasons:
        reason.data_check = check_reason(reason, a, iv_ok)
    pm = draft.valuation.price_mentioned
    price_check = None
    if pm and a.closes_near_t0:
        price_check = any(abs(c / pm - 1) <= PRICE_TOL for c in a.closes_near_t0)
    n = len(draft.reasons) or 1
    repro = sum(
        1
        for r in draft.reasons
        if r.data_check and r.data_check.reproducible in ("statements", "prices", "derived")
    )
    agreed = [
        r.data_check.agrees
        for r in draft.reasons
        if r.data_check and r.data_check.agrees is not None
    ]
    checks = {
        "price_check": price_check,
        "price_at_t0": a.price,
        "latest_fy_visible": a.fy_year,
        "reproducible_share": round(repro / n, 3),
        "reproducible_counts": {
            k: sum(1 for r in draft.reasons if r.data_check and r.data_check.reproducible == k)
            for k in ("statements", "prices", "derived", "external", "judgement")
        },
        "metrics_compared": len(agreed),
        "metrics_agree": sum(1 for x in agreed if x),
        "iv_compared": ivr.get("n_compared", 0),
        "iv_ok": ivr.get("n_ok", 0),
        "iv_within_band": iv_ok,
        "base_metric_gap_pct": (ivr.get("base_metric") or {}).get("gap_pct"),
        "expected_return_at_price": ivr.get("expected_return_at_price"),
    }
    return a, {"iv_recomputed": ivr, "checks": checks}
