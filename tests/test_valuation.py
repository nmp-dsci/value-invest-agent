"""The intrinsic-value template reproduces what the author says on camera."""

from __future__ import annotations

import pytest

from value_invest import valuation as v


def test_every_stated_iv_is_within_its_tolerance():
    rows = v.fidelity()
    assert len(rows) >= 10
    bad = [r for r in rows if not r["ok"]]
    assert not bad, bad


def test_precise_cases_are_within_six_percent():
    precise = [r for r in v.fidelity() if r["tolerance"] <= 0.06]
    assert len(precise) >= 5
    assert all(abs(r["error"]) <= 0.06 for r in precise), precise


def test_apple_weighted_scenarios_reproduce_the_hundred():
    scenarios = [
        v.Scenario("normal", 0.06, 0.06, 20, 0.70),
        v.Scenario("best", 0.10, 0.10, 40, 0.15),
        v.Scenario("worst", 0.0, 0.0, 12, 0.15),
    ]
    iv = v.scenario_iv(scenarios, base=6.0, discount_rate=0.10, payout_ratio=0.15)
    assert iv == pytest.approx(100, rel=0.08)  # he says "intrinsic value is 100"


def test_probabilities_are_normalised():
    a = [v.Scenario("n", 0.05, 0.05, 20, 0.5), v.Scenario("w", 0.0, 0.0, 12, 0.5)]
    b = [v.Scenario("n", 0.05, 0.05, 20, 1.0), v.Scenario("w", 0.0, 0.0, 12, 1.0)]
    assert v.scenario_iv(a, 6.0) == pytest.approx(v.scenario_iv(b, 6.0))


def test_expected_return_inverts_the_template():
    price = v.two_stage_iv(6.0, 0.05, 0.05, 20, 0.10, 0.15)
    assert v.expected_return(price, 6.0, 0.05, 0.05, 20, 0.15) == pytest.approx(0.10, abs=1e-4)
    # AAPL at 228 on his normal inputs: no positive return over ten years
    assert v.expected_return(228, 6.0, 0.05, 0.05, 20, 0.15) < 0.01


def test_implied_growth_matches_his_priced_in_check():
    # "the market is pricing a 40 P/E and 12 % growth" — at P/E 40 held, price 228
    g = v.implied_growth(228, 6.0, 40, 0.10, 0.15)
    assert 0.08 <= g <= 0.13


def test_buyback_yield_and_dividend_spread():
    # AAPL FY2024: 94.9 B repurchased, 15.12 B shares, close 222.64 → 2.8 %
    assert v.buyback_yield(-94.949e9, 222.64, 15.116786e9) == pytest.approx(0.028, abs=0.002)
    # VZ: $2.6 dividend on 38.35 vs 4 % treasuries → ≈ 280 bp
    assert v.dividend_spread(2.6, 38.35, 0.04) == pytest.approx(0.028, abs=0.002)


def test_quadrant_labels():
    assert v.quadrant(7, "low") == "okay return · low risk"
    assert v.quadrant(12, "high") == "good return · high risk"
