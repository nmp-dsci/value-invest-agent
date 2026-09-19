"""Golden extraction: rules, grounding against as-of data, validation bands, κ, cache key."""

from __future__ import annotations

from datetime import date

from value_invest.golden import ground as G
from value_invest.golden.kappa import kappa_report
from value_invest.golden.models import (
    Call,
    GoldenEvalDraft,
    MetricMention,
    Reason,
    Scenario,
    Valuation,
    binary_for,
    hurdle_for,
    position_for,
    title_says_buy,
)
from value_invest.golden.transcript import find_quote
from value_invest.golden.validate import verdict_for, verdict_hold_alt


def test_rules_a_b_c():
    assert position_for("fair_hold") == "HOLD" and binary_for("fair_hold") == "SELL"
    assert position_for("relative_buy") == "BUY" and position_for("too_hard") == "SELL"
    assert hurdle_for(10, "fair_hold") == "BUY" and hurdle_for(7, "fair_hold") == "HOLD"
    assert hurdle_for(6, "relative_buy") == "HOLD" and hurdle_for(None, "avoid") is None
    assert title_says_buy("Buy BlackRock Stock For a Quick 2x!") and not title_says_buy(
        "Verizon Stock Intrinsic Value"
    )


def test_find_quote_tolerates_asr_noise():
    text = "good day fellow investors the buyback yield is 3.1 % when you divide the buyback spent on the market capitalization"
    assert find_quote("the buyback yield is 3.1 % when you divide", text) == 1.0
    assert find_quote("the buyback yield is 3.1% when you divide the buy back spent", text) >= 0.9
    assert find_quote("apple will grow forever", text) < 0.6


def test_metric_names_resolve_in_his_words():
    assert G.resolve_metric_name("buyback yield") == "buyback_yield"
    assert (
        G.resolve_metric_name("P/E ratio") == "pe" and G.resolve_metric_name("peer ratio") == "pe"
    )
    assert G.resolve_metric_name("earnings per share") == "eps"
    assert G.resolve_metric_name("free cash flow") == "fcf"
    assert G.resolve_metric_name("treasuries") == "risk_free"
    assert G.resolve_metric_name("China share of sales") is None


def _seed_apple(con):
    # prices around T0 = 2025-01-21 and five years back
    con.executemany(
        "INSERT INTO vi.prices VALUES ('AAPL', ?, 1, 1, 1, ?, ?, 1)",
        [
            (date(2020, 1, 21), 75.0, 75.0),
            (date(2024, 12, 20), 250.0, 250.0),
            (date(2025, 1, 17), 229.98, 229.98),
            (date(2025, 1, 21), 222.64, 222.64),
            (date(2025, 7, 21), 210.0, 210.0),
            (date(2026, 1, 21), 245.0, 245.0),
        ],
    )
    con.executemany(
        "INSERT INTO vi.prices VALUES ('SPY', ?, 1, 1, 1, ?, ?, 1)",
        [
            (date(2025, 1, 21), 600.0, 600.0),
            (date(2025, 7, 21), 630.0, 630.0),
            (date(2026, 1, 21), 690.0, 690.0),
        ],
    )
    fy24 = date(2024, 9, 28)
    filed = date(2024, 11, 1)
    rows = [
        ("income", "Total Revenue", 391.0e9),
        ("income", "Net Income", 93.7e9),
        ("income", "Diluted EPS", 6.08),
        ("income", "Operating Income", 123.2e9),
        ("balance", "Total Assets", 365e9),
        ("balance", "Total Debt", 96.7e9),
        ("balance", "Cash And Cash Equivalents", 29.9e9),
        ("balance", "Stockholders Equity", 57e9),
        ("balance", "Shares Outstanding", 15.117e9),
        ("cashflow", "Repurchase Of Capital Stock", -94.9e9),
        ("cashflow", "Cash Dividends Paid", -15.2e9),
        ("cashflow", "Free Cash Flow", 108.8e9),
    ]
    con.executemany(
        "INSERT INTO vi.statements VALUES ('AAPL', ?, ?, 'annual', ?, ?, ?, ?, 'edgar')",
        [(fy24, k, li, v, filed, filed) for k, li, v in rows]
        + [
            (
                date(2023, 9, 30),
                "income",
                "Total Revenue",
                383.3e9,
                date(2023, 11, 3),
                date(2023, 11, 3),
            ),
            (
                date(2022, 9, 24),
                "income",
                "Total Revenue",
                394.3e9,
                date(2022, 10, 28),
                date(2022, 10, 28),
            ),
        ],
    )
    # FY2025, filed after T0: must stay invisible
    con.execute(
        "INSERT INTO vi.statements VALUES ('AAPL', ?, 'income', 'annual', 'Diluted EPS', 7.5, ?, ?, 'edgar')",
        [date(2025, 9, 27), date(2025, 10, 31), date(2025, 10, 31)],
    )
    con.execute("INSERT INTO vi.rates VALUES ('DGS10', ?, 0.046)", [date(2025, 1, 17)])


def _apple_draft() -> GoldenEvalDraft:
    return GoldenEvalDraft(
        video_id="v1",
        ticker="AAPL",
        call=Call(
            stance_detail="avoid",
            personal_action="none",
            expected_return_pct=0,
            horizon_years=10,
            conviction="high",
            headline_quote="the stock is significantly overvalued",
        ),
        valuation=Valuation(
            method="eps_multiple",
            base_metric={"name": "eps", "value_stated": 6.0, "quote": "earnings per share $6"},
            discount_rate=0.10,
            payout_ratio=0.15,
            scenarios=[
                Scenario(
                    name="normal",
                    g_y1_5=0.05,
                    g_y6_10=0.05,
                    terminal_multiple=20,
                    probability=0.7,
                    iv_stated=80,
                ),
                Scenario(
                    name="worst",
                    g_y1_5=0.0,
                    g_y6_10=0.0,
                    terminal_multiple=12,
                    probability=0.15,
                    iv_stated=34,
                ),
                Scenario(
                    name="best", g_y1_5=0.10, g_y6_10=0.10, terminal_multiple=40, probability=0.15
                ),
            ],
            iv_weighted_stated=100,
            price_mentioned=228,
        ),
        reasons=[
            Reason(
                rank=1,
                direction="for_sell",
                category="valuation",
                claim="IV 100 vs 228",
                quote="intrinsic value is 100",
                feeds="none",
            ),
            Reason(
                rank=2,
                direction="for_sell",
                category="capital_allocation",
                claim="buybacks at a premium",
                quote="the buyback yield is 3.1%",
                feeds="none",
                metrics=[
                    MetricMention(name="buyback yield", value=3.1, unit="pct"),
                    MetricMention(name="buybacks", value=110, unit="usd_bn"),
                ],
            ),
            Reason(
                rank=3,
                direction="for_sell",
                category="growth",
                claim="no growth for three years",
                quote="practically no growth",
                feeds="g_y1_5",
            ),
            Reason(
                rank=4,
                direction="for_sell",
                category="cyclicality",
                claim="China is 19 % of sales",
                quote="19% of sales are from China",
                metrics=[MetricMention(name="China share of sales", value=19, unit="pct")],
            ),
            Reason(
                rank=5,
                direction="for_sell",
                category="sentiment",
                claim="Buffett selling",
                quote="the greatest seller of Apple stock",
            ),
        ],
        external_facts_used=["consensus growth 10–12 %"],
    )


def test_ground_uses_only_data_visible_at_t0(con):
    _seed_apple(con)
    draft = _apple_draft()
    a, g = G.ground(con, draft, "AAPL", date(2025, 1, 21))
    assert a.fy_year == 2024 and a.price == 222.64  # FY2025 EPS (filed later) never leaks
    assert abs(a.metrics["buyback_yield"]["value"] - 0.0282) < 0.001
    assert abs(a.metrics["pe"]["value"] - 36.6) < 0.2
    checks = g["checks"]
    assert checks["price_check"] is True  # 228 vs 229.98 two trading days earlier
    dc = {r.rank: r.data_check for r in draft.reasons}
    assert (
        dc[2].reproducible == "derived"
        and dc[2].agrees is True
        and "not in our data" not in (dc[2].gap_note or "")
    )
    assert dc[1].reproducible == "derived" and dc[1].agrees is True  # IV recomputed within band
    assert dc[3].reproducible == "statements"
    assert dc[4].reproducible == "external"
    assert dc[5].reproducible == "external"
    assert checks["reproducible_share"] == 0.6
    ivr = g["iv_recomputed"]
    assert ivr["n_compared"] == 2 and ivr["n_ok"] == 2 and 95 <= ivr["iv_weighted_model"] <= 112
    assert ivr["base_metric"]["stated"] == 6.0 and abs(ivr["base_metric"]["as_of"] - 6.08) < 0.01
    assert ivr["expected_return_at_price"] < 2


def test_verdict_bands_follow_d14():
    assert (
        verdict_for("BUY", 0.06) == "correct"
        and verdict_for("BUY", -0.06) == "wrong"
        and verdict_for("BUY", 0.0) == "indeterminate"
    )
    assert verdict_for("SELL", -0.06) == "correct" and verdict_for("SELL", 0.2) == "wrong"
    assert (
        verdict_for("HOLD", 0.08) == "correct"
        and verdict_for("HOLD", 0.33) == "wrong"
        and verdict_for("HOLD", -0.29) == "wrong"
    )
    assert (
        verdict_hold_alt("HOLD", 0.33) == "correct" and verdict_hold_alt("HOLD", -0.07) == "wrong"
    )
    assert verdict_hold_alt("BUY", 0.06) == "correct"


def test_kappa_report():
    pairs = [
        ("avoid", "avoid"),
        ("relative_buy", "relative_buy"),
        ("fair_hold", "avoid"),
        ("short", "short"),
        ("avoid", "too_hard"),
    ]
    rep = kappa_report(pairs)
    assert rep["n"] == 5 and rep["agreement_6way"] == 0.6 and rep["agreement_3way"] == 0.8
    assert rep["kappa_3way"] is not None and rep["kappa_3way"] > rep["kappa_6way"]


def test_split_and_cache_key():
    from value_invest.golden.checkpoint import cache_key, split_for
    from value_invest.golden.versions import load_version

    assert (
        split_for("2022/23") == "train"
        and split_for("2024/25") == "test"
        and split_for("2025/26") == "holdout"
    )
    v = load_version("v0")
    k = cache_key("abc", "0123456789abcdef", v)
    assert k.startswith("abc:0123456789ab:v0:") and v.fingerprint in k


def test_draft_tolerates_text_numbers_and_key_variants():
    d = GoldenEvalDraft.model_validate(
        {
            "video_id": "x",
            "ticker": "V",
            "call": {
                "stance_detail": "fair_hold",
                "expected_return_pct": "not stated",
                "headline_quote": "q",
            },
            "valuation": {
                "method": "eps_multiple",
                "base_metric": {"name": "eps", "value_stated": "$6"},
                "discount_rate": "10%",
                "scenarios": [
                    {
                        "scenario": "normal",
                        "g_y1_5": "5 %",
                        "terminal_multiple": 20,
                        "probability": "n/a",
                    }
                ],
                "what_is_priced_in": "the market prices 12 % growth",
            },
            "reasons": [
                {
                    "rank": 1,
                    "direction": "for_sell",
                    "category": "valuation",
                    "claim": "c",
                    "quote": "q",
                    "metrics": {"pe ratio": 27},
                }
            ],
        }
    )
    assert d.call.expected_return_pct is None and d.valuation.discount_rate == 10.0
    assert d.valuation.base_metric is not None and d.valuation.base_metric.value_stated == 6.0
    assert (
        d.valuation.scenarios[0].name == "normal"
        and d.valuation.scenarios[0].g_y1_5 == 5.0
        and d.valuation.scenarios[0].probability is None
    )
    assert (
        d.valuation.what_is_priced_in is not None
        and d.valuation.what_is_priced_in.quote.startswith("the market")
    )
    assert d.reasons[0].metrics[0].name == "pe ratio" and d.reasons[0].metrics[0].value == 27


def test_draft_tolerates_unknown_feeds_and_empty_base_metric():
    d = GoldenEvalDraft.model_validate(
        {
            "video_id": "x",
            "ticker": "UNH",
            "call": {"stance_detail": "too_hard", "headline_quote": "q"},
            "valuation": {
                "method": "none",
                "base_metric": {"name": None, "value_stated": None, "quote": None},
                "what_is_priced_in": {
                    "growth": "13 to 16% forever",
                    "multiple": "20-25",
                    "quote": "x",
                },
            },
            "reasons": [
                {
                    "rank": 1,
                    "direction": "for_sell",
                    "category": "competence",
                    "claim": "c",
                    "quote": "q",
                    "feeds": "worst",
                }
            ],
        }
    )
    assert d.valuation.base_metric is None and d.reasons[0].feeds == "none"
    assert (
        d.valuation.what_is_priced_in is not None and d.valuation.what_is_priced_in.growth is None
    )
