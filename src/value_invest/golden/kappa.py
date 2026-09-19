"""Cohen's κ between two labellers, on the 6-way stance and its 3-way collapse."""

from __future__ import annotations

from collections import Counter

from value_invest.golden.models import THREE_WAY


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe == 1.0:
        return 1.0
    return round((po - pe) / (1 - pe), 4)


def kappa_report(pairs: list[tuple[str, str]]) -> dict:
    """``pairs`` are (extractor stance_detail, critic stance_detail)."""
    six_a = [p[0] for p in pairs]
    six_b = [p[1] for p in pairs]
    three_a = [THREE_WAY[s] for s in six_a]
    three_b = [THREE_WAY[s] for s in six_b]
    return {
        "n": len(pairs),
        "kappa_6way": cohen_kappa(six_a, six_b),
        "kappa_3way": cohen_kappa(three_a, three_b),
        "agreement_6way": round(sum(x == y for x, y in zip(six_a, six_b)) / max(1, len(pairs)), 3),
        "agreement_3way": round(
            sum(x == y for x, y in zip(three_a, three_b)) / max(1, len(pairs)), 3
        ),
        "disagreements": [{"extractor": x, "critic": y} for x, y in pairs if x != y],
    }
