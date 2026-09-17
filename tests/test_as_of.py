"""The point-in-time invariant: nothing dated after t0 comes back from the as-of macros."""

from datetime import date


def _seed(con):
    con.executemany(
        "INSERT INTO vi.prices VALUES (?, ?, 1, 1, 1, ?, ?, 100)",
        [("NKE", date(2024, 6, 28), 95.0, 95.0), ("NKE", date(2024, 7, 1), 75.0, 75.0), ("NKE", date(2024, 7, 3), 74.0, 74.0), ("NKE", date(2025, 1, 2), 70.0, 70.0)],
    )
    # FY2023 (period end 2023-05-31) visible from 2023-08-29; FY2024 (2024-05-31) visible from 2024-08-29
    con.executemany(
        "INSERT INTO vi.statements VALUES (?, ?, 'income', 'annual', 'Total Revenue', ?, NULL, ?, 'yfinance')",
        [("NKE", date(2023, 5, 31), 51.2e9, date(2023, 8, 29)), ("NKE", date(2024, 5, 31), 51.4e9, date(2024, 8, 29))],
    )


def test_prices_as_of_excludes_future(con):
    _seed(con)
    rows = con.execute("SELECT date FROM vi.prices_as_of('NKE', DATE '2024-07-02') ORDER BY date").fetchall()
    assert [r[0] for r in rows] == [date(2024, 6, 28), date(2024, 7, 1)]


def test_statements_as_of_uses_available_from_not_period_end(con):
    _seed(con)
    # video on 2024-07-02: FY2024 ended 2024-05-31 but is not visible until 2024-08-29
    visible = con.execute("SELECT period_end FROM vi.statements_as_of('NKE', DATE '2024-07-02')").fetchall()
    assert [r[0] for r in visible] == [date(2023, 5, 31)]
    later = con.execute("SELECT count(*) FROM vi.statements_as_of('NKE', DATE '2024-09-01')").fetchone()[0]
    assert later == 2


def test_no_leak_property(con):
    _seed(con)
    for t0 in (date(2024, 1, 1), date(2024, 7, 2), date(2024, 12, 31)):
        assert con.execute("SELECT count(*) FROM vi.prices_as_of('NKE', ?) WHERE date > ?", [t0, t0]).fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM vi.statements_as_of('NKE', ?) WHERE available_from > ?", [t0, t0]).fetchone()[0] == 0
