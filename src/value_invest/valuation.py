"""The author's intrinsic-value template, as code.

Every stock video that values a company runs the same spreadsheet: a base
per-share metric (EPS, or the dividend, or net income for Berkshire) grows at
one rate for five years and another for the next five, is capitalised at a
terminal multiple in year ten, and everything is discounted at the required
return — 10 % in every valuation read for the M2 plan. Three scenarios with
probabilities give a weighted value, which is compared with the price and
placed on his return-vs-risk quadrant.

This module is that template. ``data/golden/stated_ivs.json`` holds the values
he states on camera with the inputs he states; ``tests/test_valuation.py`` and
``vi valuation check`` keep the code within his rounding of them. The exact cell
layout of the downloadable sheet (year-0 vs year-1 timing) is still to be
pinned; until then the reconstruction below matches precise inputs within
±6 % and vague ones ("25 … perhaps 30 %") within ±12 %.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STAGE1_YEARS = 5
YEARS = 10
DEFAULT_DISCOUNT = 0.10


def two_stage_iv(
    base: float,
    g_y1_5: float,
    g_y6_10: float,
    terminal_multiple: float,
    discount_rate: float = DEFAULT_DISCOUNT,
    payout_ratio: float = 0.0,
    years: int = YEARS,
) -> float:
    """Present value per share (or per unit of ``base``).

    ``base`` grows at ``g_y1_5`` for the first five years and ``g_y6_10`` after;
    the terminal value is the year-``years`` metric times ``terminal_multiple``;
    ``payout_ratio`` of each year's metric is received as a dividend. All cash
    flows are discounted at ``discount_rate``. A dividend model is
    ``payout_ratio=1.0`` with ``base`` = dividend per share.
    """
    metric, pv_dividends = base, 0.0
    for t in range(1, years + 1):
        metric *= (1 + g_y1_5) if t <= STAGE1_YEARS else (1 + g_y6_10)
        pv_dividends += metric * payout_ratio / (1 + discount_rate) ** t
    return metric * terminal_multiple / (1 + discount_rate) ** years + pv_dividends


@dataclass(frozen=True)
class Scenario:
    name: str
    g_y1_5: float
    g_y6_10: float
    terminal_multiple: float
    probability: float
    discount_rate: float | None = None  # None → the call's discount rate

    def iv(self, base: float, discount_rate: float, payout_ratio: float = 0.0) -> float:
        return two_stage_iv(
            base,
            self.g_y1_5,
            self.g_y6_10,
            self.terminal_multiple,
            self.discount_rate if self.discount_rate is not None else discount_rate,
            payout_ratio,
        )


def scenario_iv(
    scenarios: list[Scenario],
    base: float,
    discount_rate: float = DEFAULT_DISCOUNT,
    payout_ratio: float = 0.0,
) -> float:
    """Probability-weighted intrinsic value — Σ pᵢ · IVᵢ, probabilities normalised.

    He types probabilities that sometimes sum to 105 %; normalising reproduces
    the sheet, which does the same.
    """
    total = sum(s.probability for s in scenarios)
    if total <= 0:
        raise ValueError("scenario probabilities must sum to a positive number")
    return sum(s.probability / total * s.iv(base, discount_rate, payout_ratio) for s in scenarios)


def _bisect(f: Any, lo: float, hi: float, tol: float = 1e-6, steps: int = 200) -> float:
    flo, fhi = f(lo), f(hi)
    if (flo < 0) == (fhi < 0) and abs(flo) >= tol and abs(fhi) >= tol:
        raise ValueError("no sign change between lo and hi; root is not bracketed")
    for _ in range(steps):
        mid = (lo + hi) / 2
        fm = f(mid)
        if abs(fm) < tol:
            return mid
        if (fm < 0) == (flo < 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def expected_return(
    price: float,
    base: float,
    g_y1_5: float,
    g_y6_10: float,
    terminal_multiple: float,
    payout_ratio: float = 0.0,
) -> float:
    """The discount rate at which the template's value equals ``price``.

    "Fairly valued for a 10 % return" is this number being 0.10; "priced for a
    4 % return" is it being 0.04. Solved by bisection between −50 % and +100 %.
    """
    return _bisect(
        lambda r: two_stage_iv(base, g_y1_5, g_y6_10, terminal_multiple, r, payout_ratio) - price,
        -0.5,
        1.0,
    )


def implied_growth(
    price: float,
    base: float,
    terminal_multiple: float,
    discount_rate: float = DEFAULT_DISCOUNT,
    payout_ratio: float = 0.0,
) -> float:
    """The single ten-year growth rate that the price implies at ``terminal_multiple``.

    His "what is Wall Street pricing in" check: solve for g with the multiple
    held (AAPL 2025: P/E 40 held → ≈ 12 % growth).
    """
    return _bisect(
        lambda g: two_stage_iv(base, g, g, terminal_multiple, discount_rate, payout_ratio) - price,
        -0.5,
        1.0,
    )


def buyback_yield(repurchase: float, close: float, shares: float) -> float:
    """Buybacks over market cap — "110 billion on 3.5 trillion is 3.1 %"."""
    return abs(repurchase) / (close * shares)


def dividend_spread(dps: float, close: float, risk_free: float) -> float:
    """Dividend yield minus the risk-free rate — his "≈ 300 bp over treasuries" rule."""
    return dps / close - risk_free


def quadrant(expected_return_pct: float, risk: str) -> str:
    """Where a call sits on his value-investing quadrant.

    ``risk`` is low | mid | high as he says it; the return axis is his expected
    return. Labels follow the words he uses on the chart.
    """
    if expected_return_pct >= 15:
        band = "great"
    elif expected_return_pct >= 10:
        band = "good"
    elif expected_return_pct >= 6:
        band = "okay"
    else:
        band = "low"
    return f"{band} return · {risk} risk"


STATED_IVS = Path(__file__).resolve().parents[2] / "data" / "golden" / "stated_ivs.json"


def fidelity(path: Path = STATED_IVS) -> list[dict[str, Any]]:
    """Recompute every stated intrinsic value; rows carry the error and whether it is in band."""
    cases = json.loads(path.read_text())["cases"]
    rows = []
    for c in cases:
        model = two_stage_iv(
            c["base"],
            c["g_y1_5"],
            c["g_y6_10"],
            c["terminal_multiple"],
            c.get("discount_rate", DEFAULT_DISCOUNT),
            c.get("payout_ratio", 0.0),
        )
        err = model / c["stated"] - 1
        rows.append(
            {
                "ticker": c["ticker"],
                "t0": c["t0"],
                "scenario": c["scenario"],
                "stated": c["stated"],
                "model": round(model, 2),
                "error": round(err, 4),
                "tolerance": c["tolerance"],
                "ok": abs(err) <= c["tolerance"],
            }
        )
    return rows
